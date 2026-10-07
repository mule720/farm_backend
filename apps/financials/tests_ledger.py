"""Farm money ledger: permissions, tenant isolation, idempotent postings, credit summary."""
import json
from datetime import date, timedelta

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Organization, Profile
from apps.financials import credit
from apps.financials.models import FarmTransaction
from config.schema import schema


def gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


SAVE = '''mutation($i: FarmTransactionInput!) { saveFarmTransaction(input: $i) { transaction { id type category amount date cycleRef source } } }'''
LIST = '''query($since: Date) { farmTransactions(since: $since) { id type category description amount date source } }'''
DEL = '''mutation($id: String!) { deleteFarmTransaction(id: $id) { ok } }'''
POST = '''mutation($s: String!, $items: [AutoTransactionInput!]!) { postFarmTransactions(source: $s, items: $items) { created duplicates rejected } }'''


def tx(**o):
    d = dict(type='expense', category='feed', description='Starter feed', amount=250.5, date='2026-10-01')
    d.update(o)
    return d


def auto(ref, **o):
    d = dict(sourceRef=ref, type='expense', category='feed', description='Purchase', amount=100, date='2026-10-01')
    d.update(o)
    return d


class LedgerTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Choma', slug='choma', org_type='farm', business_type='farmer')
        self.other = Organization.objects.create(name='Other', slug='other', org_type='farm', business_type='farmer')
        mk = lambda e, org, role, **k: Profile.objects.create_user(email=e, full_name=e, password='pw12345678', phone='0970000' + str(abs(hash(e)) % 10**5).zfill(5), organization=org, role=role, **k)
        self.owner = mk('o@x.test', self.org, 'director', is_org_admin=True)
        self.owner2 = mk('o2@x.test', self.org, 'director')
        self.fin = mk('f@x.test', self.org, 'finance_manager')
        self.hand = mk('h@x.test', self.org, 'farmhand')
        self.sales = mk('s@x.test', self.org, 'sales_manager')
        self.stranger = mk('z@x.test', self.other, 'director')

    # ── manual entries ────────────────────────────────────────────────────
    def test_create_edit_delete_roundtrip(self):
        r = gql(self.owner, SAVE, {'i': tx(cycleRef='cycle-1')})
        self.assertIsNone(r.errors, r.errors)
        t = r.data['saveFarmTransaction']['transaction']
        self.assertEqual((t['type'], t['amount'], t['source'], t['cycleRef']), ('expense', 250.5, 'manual', 'cycle-1'))
        r = gql(self.owner2, SAVE, {'i': tx(id=t['id'], amount=300, description='Starter feed 60 bags')})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['saveFarmTransaction']['transaction']['amount'], 300)
        rows = gql(self.owner, LIST).data['farmTransactions']
        self.assertEqual(len(rows), 1)
        self.assertIsNone(gql(self.owner, DEL, {'id': t['id']}).errors)
        self.assertEqual(gql(self.owner, LIST).data['farmTransactions'], [])

    def test_validation(self):
        for bad in (tx(type='transfer'), tx(category='sale_income'), tx(type='income', category='feed'),
                    tx(amount=0), tx(amount=-5), tx(description='   ')):
            self.assertTrue(gql(self.owner, SAVE, {'i': bad}).errors, bad)
        self.assertEqual(FarmTransaction.objects.count(), 0)

    # ── permissions ───────────────────────────────────────────────────────
    def test_finance_permissions(self):
        self.assertIsNone(gql(self.fin, SAVE, {'i': tx()}).errors)           # finance manager: create
        self.assertTrue(gql(self.hand, SAVE, {'i': tx()}).errors)            # farmhand: no finance
        self.assertTrue(gql(self.hand, LIST).errors)
        self.assertTrue(gql(self.sales, LIST).errors)
        self.assertIsNone(gql(self.fin, LIST).errors)
        t = FarmTransaction.objects.get()
        self.assertTrue(gql(self.fin, DEL, {'id': str(t.id)}).errors)        # finance manager cannot delete (RW only)
        self.assertIsNone(gql(self.owner, DEL, {'id': str(t.id)}).errors)    # director can
        self.assertTrue(gql(AnonymousUser(), LIST).errors)

    # ── tenant isolation ──────────────────────────────────────────────────
    def test_other_org_is_invisible_and_untouchable(self):
        t = gql(self.owner, SAVE, {'i': tx()}).data['saveFarmTransaction']['transaction']
        self.assertEqual(gql(self.stranger, LIST).data['farmTransactions'], [])
        self.assertTrue(gql(self.stranger, SAVE, {'i': tx(id=t['id'], amount=1)}).errors)
        self.assertTrue(gql(self.stranger, DEL, {'id': t['id']}).errors)
        self.assertTrue(gql(self.owner, DEL, {'id': 'not-a-uuid'}).errors)
        self.assertEqual(FarmTransaction.objects.get().amount, 250.5)

    # ── automatic postings ────────────────────────────────────────────────
    def test_auto_posting_is_idempotent(self):
        items = [auto('prod:e1:purchase', amount=500), auto('prod:e2:sale', type='income', category='sale_income', amount=900)]
        r = gql(self.owner, POST, {'s': 'production', 'items': items})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['postFarmTransactions'], {'created': 2, 'duplicates': 0, 'rejected': 0})
        r = gql(self.owner, POST, {'s': 'production', 'items': items})
        self.assertEqual(r.data['postFarmTransactions'], {'created': 0, 'duplicates': 2, 'rejected': 0})
        self.assertEqual(FarmTransaction.objects.count(), 2)
        self.assertEqual({t.source for t in FarmTransaction.objects.all()}, {'production'})

    def test_two_orgs_may_use_the_same_key(self):
        gql(self.owner, POST, {'s': 'sales', 'items': [auto('order:1')]})
        r = gql(self.stranger, POST, {'s': 'sales', 'items': [auto('order:1')]})
        self.assertEqual(r.data['postFarmTransactions']['created'], 1)

    def test_bad_items_are_rejected_not_fatal(self):
        items = [auto('a'), auto('b', amount=0), auto('c', category='nonsense'), auto('')]
        r = gql(self.owner, POST, {'s': 'production', 'items': items})
        self.assertEqual(r.data['postFarmTransactions'], {'created': 1, 'duplicates': 0, 'rejected': 3})

    def test_who_may_post_what(self):
        # a farmhand logs production events, so can post production costs, but not sales or imports
        self.assertIsNone(gql(self.hand, POST, {'s': 'production', 'items': [auto('p1')]}).errors)
        self.assertTrue(gql(self.hand, POST, {'s': 'sales', 'items': [auto('p2')]}).errors)
        self.assertTrue(gql(self.hand, POST, {'s': 'import', 'items': [auto('p3')]}).errors)
        # a sales manager posts sales income
        self.assertIsNone(gql(self.sales, POST, {'s': 'sales', 'items': [auto('s1', type='income', category='sale_income')]}).errors)
        self.assertTrue(gql(self.sales, POST, {'s': 'production', 'items': [auto('s2')]}).errors)
        # finance manager may import
        self.assertIsNone(gql(self.fin, POST, {'s': 'import', 'items': [auto('i1')]}).errors)
        self.assertTrue(gql(self.owner, POST, {'s': 'manual', 'items': [auto('m1')]}).errors)
        # and the farmhand cannot read what they posted
        self.assertTrue(gql(self.hand, LIST).errors)

    # ── credit summary ────────────────────────────────────────────────────
    def test_credit_summary_uses_the_ledger(self):
        base = credit.compute_credit_summary(self.org)
        self.assertEqual(base['financials']['basis'], 'batches')
        self.assertEqual(base['financials']['revenue_12m'], 0)
        today = date.today()
        for i in range(4):  # four months, each profitable
            d = today - timedelta(days=30 * i + 2)
            FarmTransaction.objects.create(organization=self.org, tx_type='expense', category='feed', description='Feed', amount=1000, date=d)
            FarmTransaction.objects.create(organization=self.org, tx_type='income', category='sale_income', description='Sale', amount=1800, date=d)
        s = credit.compute_credit_summary(self.org)
        f = s['financials']
        self.assertEqual(f['basis'], 'ledger')
        self.assertEqual((f['revenue_12m'], f['costs_12m'], f['profit_12m']), (7200.0, 4000.0, 3200.0))
        self.assertEqual(f['roi_pct_12m'], 80.0)
        self.assertEqual((f['profitable_batches'], f['scored_batches']), (4, 4))
        prof = next(x for x in s['factors'] if x['key'] == 'profitability')
        self.assertGreater(prof['score'], 0)
        self.assertIn('months profitable', prof['evidence'])

    def test_credit_summary_ignores_other_orgs(self):
        FarmTransaction.objects.create(organization=self.other, tx_type='expense', category='feed', description='x', amount=999, date=date.today())
        self.assertEqual(credit.compute_credit_summary(self.org)['financials']['costs_12m'], 0)

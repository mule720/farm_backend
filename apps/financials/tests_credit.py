"""Credit summary + lender sharing tests."""
import json
import os
import tempfile
from datetime import date, timedelta

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Organization, Profile
from apps.enterprises.models import Enterprise, EnterpriseBatch
from apps.production.models import ProductionRecord
from apps.financials.models import BatchFinancials, CostEntry, RevenueEntry, CreditShareGrant, LoanApplication
from apps.financials import credit
from apps.market.models import BuyerProfile, TradeContract
from config.schema import schema

TMP = tempfile.mkdtemp(prefix='agrinuxes_credit_')


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


def _farm(name, slug, consent=True):
    org = Organization.objects.create(name=name, slug=slug, org_type='farm', province='Lusaka', district='Chongwe', data_sharing_consent=consent)
    d = Profile.objects.create_user(email=f'{slug}@t.test', full_name='D', password='pw12345678', phone=f'097{abs(hash(slug)) % 10**7:07d}', organization=org, role='director')
    return org, d


def _build_history(org, user, months=10, roi=0.5):
    """Records every month for `months`, one profitable batch financials per quarter."""
    today = date.today()
    ent = Enterprise.objects.create(organization=org, name='Maize', category='crop', production_type='maize', created_by=user)
    for i in range(months):
        d = today - timedelta(days=30 * i + 3)
        b = EnterpriseBatch.objects.create(organization=org, enterprise=ent, name=f'B{i}', start_date=d, status='completed' if i else 'active', created_by=user)
        for k in range(3):
            ProductionRecord.objects.create(organization=org, enterprise=ent, batch=b, record_date=d - timedelta(days=k * 7), record_type='daily', data={}, recorded_by=user)
    for q in range(3):
        start = today - timedelta(days=90 * q + 80)
        bf = BatchFinancials.objects.create(organization=org, enterprise=ent, batch_name=f'Q{q}', start_date=start, end_date=start + timedelta(days=75), created_by=user)
        CostEntry.objects.create(organization=org, batch_financials=bf, category='feed', description='inputs', amount=10000, entry_date=start, created_by=user)
        RevenueEntry.objects.create(organization=org, batch_financials=bf, category='sales_crop', description='sale', amount=10000 * (1 + roi), entry_date=start + timedelta(days=70), created_by=user)
    return ent


class CreditScoreTest(TestCase):
    def test_empty_farm_is_thin_file_band_e(self):
        org, d = _farm('New Farm', 'new-farm', consent=False)
        s = credit.compute_credit_summary(org)
        self.assertEqual(s['band'], 'E')
        self.assertTrue(s['thin_file'])
        self.assertLess(s['score'], 15)
        self.assertEqual(len(s['factors']), 5)
        self.assertEqual(sum(f['weight'] for f in s['factors']), 100)

    def test_established_profitable_farm_scores_well(self):
        org, d = _farm('Good Farm', 'good-farm')
        Organization.objects.filter(pk=org.pk).update(created_at=timezone.now() - timedelta(days=800))
        org.refresh_from_db()
        _build_history(org, d, months=12, roi=0.6)
        buyer = BuyerProfile.objects.create(organization=org, name='Verified Co', is_verified=True, country='Zambia')
        for i in range(4):
            TradeContract.objects.create(organization=org, buyer=buyer, commodity='Maize', quantity_agreed=1000, agreed_price=5, status='fulfilled', created_by=d)
        s = credit.compute_credit_summary(org)
        self.assertGreaterEqual(s['score'], 65, s['factors'])
        self.assertIn(s['band'], ('A', 'B'))
        self.assertFalse(s['thin_file'])
        f = {x['key']: x for x in s['factors']}
        self.assertGreater(f['record_consistency']['score'], 20)
        self.assertGreater(f['profitability']['score'], 15)
        self.assertGreater(f['trading_history']['score'], 10)
        self.assertEqual(s['records']['active_months_12'], 12)
        self.assertEqual(s['financials']['profitable_batches'], 3)
        self.assertAlmostEqual(s['financials']['roi_pct_12m'], 60.0)
        self.assertEqual(s['trading']['contracts_fulfilled'], 4)
        self.assertEqual(s['trading']['verified_buyers'], 1)
        self.assertEqual(len(s['financials']['monthly_revenue']), 12)

    def test_loss_making_and_disputed_lowers_score(self):
        org, d = _farm('Bad Farm', 'bad-farm')
        _build_history(org, d, months=12, roi=-0.3)
        buyer = BuyerProfile.objects.create(organization=org, name='B', country='Zambia')
        TradeContract.objects.create(organization=org, buyer=buyer, commodity='Maize', quantity_agreed=1, agreed_price=1, status='disputed', created_by=d)
        TradeContract.objects.create(organization=org, buyer=buyer, commodity='Maize', quantity_agreed=1, agreed_price=1, status='fulfilled', created_by=d)
        s = credit.compute_credit_summary(org)
        f = {x['key']: x for x in s['factors']}
        self.assertLess(f['profitability']['score'], 10)
        self.assertEqual(s['trading']['fulfilment_rate_pct'], 50)
        self.assertEqual(s['financials']['profitable_batches'], 0)

    def test_default_penalises_verification(self):
        org, d = _farm('Def Farm', 'def-farm')
        base = credit.compute_credit_summary(org)['factors'][4]['score']
        LoanApplication.objects.create(organization=org, lender_name='X', amount_requested=1000, purpose='p', status='defaulted')
        after = credit.compute_credit_summary(org)['factors'][4]['score']
        self.assertLess(after, base)
        self.assertIn('DEFAULT', credit.compute_credit_summary(org)['factors'][4]['evidence'])


@override_settings(MEDIA_ROOT=TMP, MEDIA_URL='/media/')
class CreditSharingTest(TestCase):
    def setUp(self):
        self.org, self.director = _farm('Share Farm', 'share-farm')
        _build_history(self.org, self.director, months=6)
        self.hand = Profile.objects.create_user(email='hand@share.test', full_name='H', password='pw12345678', phone='0966000001', organization=self.org, role='farmhand')
        self.other_org, self.other = _farm('Other', 'other-share')

    def test_my_summary_requires_farm_account(self):
        q = 'query { myCreditSummary { score band summary } }'
        self.assertTrue(_gql(None, q).errors)
        r = _gql(self.director, q)
        self.assertIsNone(r.errors, r.errors)
        self.assertIn('factors', json.loads(r.data['myCreditSummary']['summary']))
        gov = Organization.objects.create(name='Gov', slug='gov-c', org_type='government')
        viewer = Profile.objects.create_user(email='g@c.test', full_name='G', password='pw12345678', phone='0955000002', organization=gov, role='gov_viewer')
        self.assertTrue(_gql(viewer, q).errors)

    def test_share_grant_lifecycle(self):
        m = 'mutation($n: String!, $d: Int) { createCreditShareGrant(lenderName: $n, lenderContact: "loans@zanaco.test", purpose: "Seasonal input loan", validDays: $d) { grant { id token expiresAt isActive shareUrlPath } } }'
        self.assertTrue(_gql(self.hand, m, {'n': 'Zanaco'}).errors)  # farmhand cannot share
        r = _gql(self.director, m, {'n': 'Zanaco', 'd': 14})
        self.assertIsNone(r.errors, r.errors)
        g = r.data['createCreditShareGrant']['grant']
        self.assertTrue(g['isActive'])
        self.assertGreaterEqual(len(g['token']), 40)
        self.assertEqual(g['shareUrlPath'], f"/?credit={g['token']}")

        # Lender (anonymous) reads via token
        q = 'query($t: String!) { lenderCreditReport(token: $t) { score band summary } }'
        r = _gql(None, q, {'t': g['token']})
        self.assertIsNone(r.errors, r.errors)
        s = json.loads(r.data['lenderCreditReport']['summary'])
        self.assertEqual(s['farm']['name'], 'Share Farm')
        self.assertEqual(s['shared_with']['lender'], 'Zanaco')
        grant = CreditShareGrant.objects.get(pk=g['id'])
        self.assertEqual(grant.access_count, 1)
        self.assertIsNotNone(grant.last_accessed_at)

        # Bad / revoked / expired tokens
        self.assertTrue('Invalid' in str(_gql(None, q, {'t': 'x' * 40}).errors[0]))
        self.assertTrue(_gql(None, q, {'t': 'short'}).errors)
        self.assertTrue(_gql(self.other, 'mutation($id: UUID!) { revokeCreditShareGrant(id: $id) { ok } }', {'id': g['id']}).errors)  # other org cannot revoke
        r = _gql(self.director, 'mutation($id: UUID!) { revokeCreditShareGrant(id: $id) { ok } }', {'id': g['id']})
        self.assertTrue(r.data['revokeCreditShareGrant']['ok'])
        self.assertTrue('revoked' in str(_gql(None, q, {'t': g['token']}).errors[0]))
        CreditShareGrant.objects.filter(pk=g['id']).update(is_revoked=False, expires_at=timezone.now() - timedelta(minutes=1))
        self.assertTrue('expired' in str(_gql(None, q, {'t': g['token']}).errors[0]))

        # Listing is org-scoped
        self.assertEqual(len(_gql(self.director, 'query { creditShareGrants { id } }').data['creditShareGrants']), 1)
        self.assertEqual(_gql(self.other, 'query { creditShareGrants { id } }').data['creditShareGrants'], [])

    def test_valid_days_clamped(self):
        m = 'mutation { createCreditShareGrant(lenderName: "X", validDays: 999) { grant { expiresAt } } }'
        r = _gql(self.director, m)
        exp = r.data['createCreditShareGrant']['grant']['expiresAt']
        from datetime import datetime
        self.assertLessEqual((datetime.fromisoformat(exp) - timezone.now()).days, 180)

    def test_pdf(self):
        r = _gql(self.director, 'mutation { generateCreditSummaryPdf(forLender: "Zanaco") { url } }')
        self.assertIsNone(r.errors, r.errors)
        url = r.data['generateCreditSummaryPdf']['url']
        path = os.path.join(TMP, 'credit', os.path.basename(url))
        self.assertTrue(os.path.exists(path))
        with open(path, 'rb') as f:
            self.assertEqual(f.read(5), b'%PDF-')
        self.assertGreater(os.path.getsize(path), 2000)

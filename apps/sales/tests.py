"""Sales: customers, orders, payments, ledger posting, permissions, tenant isolation, legacy import."""
import json
from datetime import date, timedelta

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Organization, Profile
from apps.financials.models import FarmTransaction
from apps.sales.models import SaleCustomer, SaleOrder, SalePayment
from config.schema import schema


def gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


ORDER_FIELDS = 'id orderNumber customerId customerName status paymentStatus lines subtotal taxPct discountAmt total amountPaid cycleRef notes dueDate payments { amount note recordedBy }'
CUST = 'mutation($i: SaleCustomerInput!) { saveSaleCustomer(input: $i) { customer { id name type phone } } }'
DELC = 'mutation($id: String!) { deleteSaleCustomer(id: $id) { ok } }'
NEW = 'mutation($i: SaleOrderInput!) { createSaleOrder(input: $i) { order { %s } } }' % ORDER_FIELDS
UPD = 'mutation($id: String!, $s: String, $n: String) { updateSaleOrder(id: $id, status: $s, notes: $n) { order { %s } } }' % ORDER_FIELDS
PAY = 'mutation($o: String!, $a: Float!, $n: String) { recordSalePayment(orderId: $o, amount: $a, note: $n) { order { %s } } }' % ORDER_FIELDS
ORDERS = 'query { saleOrders { id orderNumber status total } }'
CUSTS = 'query { saleCustomers { id name } }'
IMPORT = '''mutation($c: [LegacyCustomerInput!]!, $o: [LegacyOrderInput!]!) {
  importSalesData(customers: $c, orders: $o) { customersCreated ordersCreated skipped rejected } }'''


def line(desc='Broilers', qty=10, price=85.0, unit='head'):
    return {'description': desc, 'qty': qty, 'unit': unit, 'unitPrice': price}


def order_in(**o):
    d = dict(newCustomerName='Mulenga Butchery', date=date.today().isoformat(), lines=[line()])
    d.update(o)
    return d


class SalesTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Choma', slug='choma', org_type='farm', business_type='farmer')
        self.other = Organization.objects.create(name='Other', slug='other', org_type='farm', business_type='farmer')
        mk = lambda e, org, role, **k: Profile.objects.create_user(email=e, full_name=e, password='pw12345678', phone='0971' + str(abs(hash(e)) % 10**6).zfill(6), organization=org, role=role, **k)
        self.owner = mk('o@x.test', self.org, 'director', is_org_admin=True)
        self.sales = mk('s@x.test', self.org, 'sales_manager')
        self.hand = mk('h@x.test', self.org, 'farmhand')
        self.stranger = mk('z@x.test', self.other, 'director')

    def make_order(self, user=None, **o):
        r = gql(user or self.owner, NEW, {'i': order_in(**o)})
        self.assertIsNone(r.errors, r.errors)
        return r.data['createSaleOrder']['order']

    # ── orders ────────────────────────────────────────────────────────────
    def test_totals_and_numbers_are_computed_on_the_server(self):
        o = self.make_order(lines=[line(qty=10, price=85), line('Eggs', 30, 2.5, 'tray')], taxPct=10, discountAmt=20)
        self.assertEqual(o['subtotal'], 925.0)                 # 850 + 75
        self.assertEqual(o['total'], 997.5)                    # 925 * 1.10 - 20
        self.assertEqual((o['status'], o['paymentStatus'], o['amountPaid']), ('draft', 'unpaid', 0))
        n = date.today().strftime('ORD-%Y%m-')
        self.assertEqual(o['orderNumber'], n + '001')
        self.assertEqual(self.make_order()['orderNumber'], n + '002')
        self.assertEqual(SaleCustomer.objects.filter(name='Mulenga Butchery').count(), 2)  # each call added one

    def test_existing_customer_and_validation(self):
        c = gql(self.owner, CUST, {'i': {'name': 'Kafue Meats', 'type': 'wholesale', 'phone': '+260971'}}).data['saveSaleCustomer']['customer']
        o = self.make_order(customerId=c['id'], newCustomerName=None)
        self.assertEqual(o['customerName'], 'Kafue Meats')
        for bad in (order_in(lines=[]), order_in(lines=[line(desc='  ')]), order_in(lines=[line(qty=0)]), order_in(lines=[line(price=-1)]),
                    order_in(taxPct=150), order_in(discountAmt=-5), order_in(newCustomerName=None),
                    order_in(dueDate=(date.today() - timedelta(days=3)).isoformat()), order_in(customerId='not-a-uuid', newCustomerName=None)):
            self.assertTrue(gql(self.owner, NEW, {'i': bad}).errors, bad)

    def test_status_flow_is_enforced(self):
        o = self.make_order()
        for s in ('fulfilled',):
            self.assertTrue(gql(self.owner, UPD, {'id': o['id'], 's': s}).errors)   # draft cannot jump to fulfilled
        self.assertEqual(gql(self.owner, UPD, {'id': o['id'], 's': 'confirmed'}).data['updateSaleOrder']['order']['status'], 'confirmed')
        self.assertEqual(gql(self.owner, UPD, {'id': o['id'], 's': 'fulfilled'}).data['updateSaleOrder']['order']['status'], 'fulfilled')
        for s in ('cancelled', 'draft', 'confirmed'):
            self.assertTrue(gql(self.owner, UPD, {'id': o['id'], 's': s}).errors, s)  # fulfilled is final
        c = self.make_order()
        gql(self.owner, UPD, {'id': c['id'], 's': 'cancelled'})
        self.assertTrue(gql(self.owner, UPD, {'id': c['id'], 's': 'confirmed'}).errors)
        self.assertEqual(gql(self.owner, UPD, {'id': c['id'], 'n': 'called the buyer'}).data['updateSaleOrder']['order']['notes'], 'called the buyer')

    def test_fulfilling_posts_income_to_the_ledger_once(self):
        o = self.make_order(cycleRef='cycle-9', lines=[line(qty=4, price=250)])
        gql(self.owner, UPD, {'id': o['id'], 's': 'confirmed'})
        self.assertEqual(FarmTransaction.objects.count(), 0)                         # nothing until it is fulfilled
        gql(self.owner, UPD, {'id': o['id'], 's': 'fulfilled'})
        t = FarmTransaction.objects.get()
        self.assertEqual((t.tx_type, t.category, float(t.amount), t.cycle_ref, t.reference, t.source),
                         ('income', 'sale_income', 1000.0, 'cycle-9', o['orderNumber'], 'sales'))
        self.assertEqual(t.source_ref, f"sale:{o['id']}")
        gql(self.owner, UPD, {'id': o['id'], 'n': 'again'})                           # touching it again must not repost
        self.assertEqual(FarmTransaction.objects.count(), 1)

    def test_a_sales_manager_can_fulfil_without_finance_access(self):
        o = self.make_order(user=self.sales)
        gql(self.sales, UPD, {'id': o['id'], 's': 'confirmed'})
        self.assertIsNone(gql(self.sales, UPD, {'id': o['id'], 's': 'fulfilled'}).errors)
        self.assertEqual(FarmTransaction.objects.count(), 1)

    # ── payments ──────────────────────────────────────────────────────────
    def test_payments(self):
        o = self.make_order(lines=[line(qty=10, price=100)])      # total 1000
        r = gql(self.owner, PAY, {'o': o['id'], 'a': 400, 'n': 'cash'}).data['recordSalePayment']['order']
        self.assertEqual((r['amountPaid'], r['paymentStatus']), (400, 'partial'))
        self.assertEqual([(p['amount'], p['note']) for p in r['payments']], [(400, 'cash')])
        self.assertTrue(gql(self.owner, PAY, {'o': o['id'], 'a': 700}).errors)       # more than the balance
        self.assertTrue(gql(self.owner, PAY, {'o': o['id'], 'a': 0}).errors)
        r = gql(self.owner, PAY, {'o': o['id'], 'a': 600}).data['recordSalePayment']['order']
        self.assertEqual((r['amountPaid'], r['paymentStatus']), (1000, 'paid'))
        self.assertTrue(gql(self.owner, PAY, {'o': o['id'], 'a': 1}).errors)         # nothing left to pay
        c = self.make_order()
        gql(self.owner, UPD, {'id': c['id'], 's': 'cancelled'})
        self.assertTrue(gql(self.owner, PAY, {'o': c['id'], 'a': 10}).errors)        # cancelled orders take no payments

    def test_overdue_is_worked_out_from_the_due_date(self):
        past = date.today() - timedelta(days=2)
        o = self.make_order(date=(past - timedelta(days=5)).isoformat(), dueDate=past.isoformat())
        self.assertEqual(o['paymentStatus'], 'overdue')
        r = gql(self.owner, PAY, {'o': o['id'], 'a': 100}).data['recordSalePayment']['order']
        self.assertEqual(r['paymentStatus'], 'overdue')                                # part-paid but still late
        total = r['total']
        r = gql(self.owner, PAY, {'o': o['id'], 'a': total - 100}).data['recordSalePayment']['order']
        self.assertEqual(r['paymentStatus'], 'paid')

    # ── customers ─────────────────────────────────────────────────────────
    def test_customer_edit_and_delete_keep_orders(self):
        o = self.make_order()
        cid = o['customerId']
        r = gql(self.owner, CUST, {'i': {'id': cid, 'name': 'Mulenga & Sons', 'type': 'business'}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(SaleOrder.objects.get().customer_name, 'Mulenga & Sons')   # name follows the customer
        self.assertIsNone(gql(self.owner, DELC, {'id': cid}).errors)
        so = SaleOrder.objects.get()
        self.assertIsNone(so.customer_id)
        self.assertEqual(so.customer_name, 'Mulenga & Sons')                          # but the order keeps it
        self.assertTrue(gql(self.owner, CUST, {'i': {'name': '  '}}).errors)
        self.assertTrue(gql(self.owner, CUST, {'i': {'name': 'X', 'type': 'alien'}}).errors)

    # ── permissions & tenants ─────────────────────────────────────────────
    def test_permissions(self):
        self.assertTrue(gql(self.hand, ORDERS).errors)                                # farmhand: no sales access
        self.assertTrue(gql(self.hand, NEW, {'i': order_in()}).errors)
        self.assertTrue(gql(AnonymousUser(), ORDERS).errors)
        o = self.make_order(user=self.sales)
        self.assertEqual(len(gql(self.sales, ORDERS).data['saleOrders']), 1)
        cid = o['customerId']
        self.assertTrue(gql(self.sales, DELC, {'id': cid}).errors)                    # sales manager: no delete
        self.assertIsNone(gql(self.owner, DELC, {'id': cid}).errors)

    def test_other_organisations_cannot_see_or_change_anything(self):
        o = self.make_order()
        self.assertEqual(gql(self.stranger, ORDERS).data['saleOrders'], [])
        self.assertEqual(gql(self.stranger, CUSTS).data['saleCustomers'], [])
        self.assertTrue(gql(self.stranger, UPD, {'id': o['id'], 's': 'confirmed'}).errors)
        self.assertTrue(gql(self.stranger, PAY, {'o': o['id'], 'a': 5}).errors)
        self.assertTrue(gql(self.stranger, NEW, {'i': order_in(customerId=o['customerId'], newCustomerName=None)}).errors)
        self.assertTrue(gql(self.stranger, DELC, {'id': o['customerId']}).errors)
        self.assertEqual(SaleOrder.objects.get().status, 'draft')
        self.assertEqual(self.make_order(user=self.stranger)['orderNumber'][-3:], '001')   # numbering is per company

    # ── legacy import ─────────────────────────────────────────────────────
    def legacy(self):
        customers = [{'legacyId': 'c1', 'name': 'Old Buyer', 'type': 'wholesale'}, {'legacyId': 'c2', 'name': 'Another'}]
        orders = [
            {'legacyId': 'o1', 'orderNumber': 'ORD-202609-123', 'legacyCustomerId': 'c1', 'customerName': 'Old Buyer', 'date': '2026-09-20',
             'status': 'fulfilled', 'lines': [line(qty=5, price=200)], 'amountPaid': 400},
            {'legacyId': 'o2', 'orderNumber': 'ORD-202609-124', 'legacyCustomerId': 'gone', 'customerName': 'Deleted Customer', 'date': '2026-09-22',
             'status': 'confirmed', 'lines': [line(qty=1, price=50)], 'amountPaid': 9999},      # paid more than the total: clamped
            {'legacyId': 'o3', 'date': '2026-09-23', 'lines': []},                              # invalid: no lines
        ]
        return customers, orders

    def test_legacy_import_is_idempotent_and_does_not_touch_the_ledger(self):
        c, o = self.legacy()
        r = gql(self.owner, IMPORT, {'c': c, 'o': o}).data['importSalesData']
        self.assertEqual(r, {'customersCreated': 2, 'ordersCreated': 2, 'skipped': 0, 'rejected': 1})
        fulfilled = SaleOrder.objects.get(legacy_id='o1')
        self.assertEqual((fulfilled.status, float(fulfilled.total), float(fulfilled.amount_paid), fulfilled.customer.name),
                         ('fulfilled', 1000.0, 400.0, 'Old Buyer'))
        self.assertEqual(SalePayment.objects.filter(order=fulfilled).count(), 1)
        clamped = SaleOrder.objects.get(legacy_id='o2')
        self.assertEqual((float(clamped.amount_paid), clamped.customer_name, clamped.customer_id), (50.0, 'Deleted Customer', None))
        self.assertEqual(FarmTransaction.objects.count(), 0)                                  # old fulfilments are already in the ledger
        r = gql(self.owner, IMPORT, {'c': c, 'o': o}).data['importSalesData']
        self.assertEqual((r['customersCreated'], r['ordersCreated'], r['skipped']), (0, 0, 4))
        self.assertEqual(SaleOrder.objects.count(), 2)

    def test_import_keeps_order_numbers_unique(self):
        gql(self.owner, IMPORT, {'c': [], 'o': [{'legacyId': 'a', 'orderNumber': 'ORD-202609-001', 'customerName': 'A', 'date': '2026-09-01', 'lines': [line()]}]})
        r = gql(self.owner, IMPORT, {'c': [], 'o': [{'legacyId': 'b', 'orderNumber': 'ORD-202609-001', 'customerName': 'B', 'date': '2026-09-02', 'lines': [line()]}]})
        self.assertEqual(r.data['importSalesData']['ordersCreated'], 1)
        self.assertEqual(sorted(SaleOrder.objects.values_list('order_number', flat=True)), ['ORD-202609-001', 'ORD-202609-002'])

    def test_import_needs_sales_create(self):
        c, o = self.legacy()
        self.assertTrue(gql(self.hand, IMPORT, {'c': c, 'o': o}).errors)

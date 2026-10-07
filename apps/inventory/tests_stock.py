"""Stock: items, movements, automatic postings, permissions, tenant isolation, legacy import, sales link."""
import json
from datetime import date

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import Organization, Profile
from apps.inventory.models import InventoryItem, InventoryTransaction
from apps.inventory.service import infer_category, slug
from config.schema import schema


def gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


ITEM = 'id name sku category unit currentQty minStockLevel costPerUnit location supplier expiryDate notes'
SAVE = 'mutation($i: StockItemInput!) { saveStockItem(input: $i) { item { %s } } }' % ITEM
DEL = 'mutation($id: String!) { deleteStockItem(id: $id) { ok } }'
MOVE = '''mutation($i: String!, $t: String!, $q: Float!, $d: Date, $r: String, $dest: String, $c: Float, $n: String) {
  recordStockMovement(itemId: $i, type: $t, qty: $q, date: $d, reference: $r, destination: $dest, unitCost: $c, notes: $n) {
    item { id currentQty } movement { id type qty date reference destination unitCost notes source recordedBy } } }'''
ITEMS = 'query { stockItems { %s } }' % ITEM
MOVES = 'query($i: String!) { stockMovements(itemId: $i) { type qty date notes source } }'
POST = 'mutation($s: String!, $items: [AutoStockInput!]!) { postStock(source: $s, items: $items) { created duplicates unmatched rejected } }'
IMPORT = '''mutation($i: [LegacyItemInput!]!, $m: [LegacyMovementInput!]!) {
  importStockData(items: $i, movements: $m) { itemsCreated movementsCreated skipped rejected } }'''
UPD = 'mutation($id: String!, $s: String) { updateSaleOrder(id: $id, status: $s) { order { id status } } }'
NEW_ORDER = 'mutation($i: SaleOrderInput!) { createSaleOrder(input: $i) { order { id } } }'


def item_in(**o):
    d = dict(name='Broiler Starter Feed', category='feed', unit='bag', openingQty=20, minStockLevel=5, costPerUnit=350, location='Store A', supplier='ABC Feeds')
    d.update(o)
    return d


def auto(ref, name='Broiler Starter Feed', direction='in', qty=5, **o):
    d = dict(sourceRef=ref, direction=direction, name=name, qty=qty, unit='bag', date=date.today().isoformat())
    d.update(o)
    return d


class StockTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Choma', slug='choma', org_type='farm', business_type='farmer')
        self.other = Organization.objects.create(name='Other', slug='other', org_type='farm', business_type='farmer')
        mk = lambda e, org, role, **k: Profile.objects.create_user(email=e, full_name=e, password='pw12345678', phone='0972' + str(abs(hash(e)) % 10**6).zfill(6), organization=org, role=role, **k)
        self.owner = mk('o@x.test', self.org, 'director', is_org_admin=True)
        self.prod = mk('p@x.test', self.org, 'production_manager')       # inventory RW, no delete
        self.hand = mk('h@x.test', self.org, 'farmhand')                 # no inventory access; logs production
        self.sales = mk('s@x.test', self.org, 'sales_manager')           # sales RW; inventory view only
        self.stranger = mk('z@x.test', self.other, 'director')

    def make_item(self, user=None, **o):
        r = gql(user or self.owner, SAVE, {'i': item_in(**o)})
        self.assertIsNone(r.errors, r.errors)
        return r.data['saveStockItem']['item']

    def stock(self, item_id):
        return float(InventoryItem.objects.get(pk=item_id).current_stock)

    # ── items ─────────────────────────────────────────────────────────────
    def test_create_with_opening_stock_shows_in_history(self):
        it = self.make_item()
        self.assertEqual((it['currentQty'], it['minStockLevel'], it['costPerUnit'], it['location'], it['category']), (20.0, 5.0, 350.0, 'Store A', 'feed'))
        mv = gql(self.owner, MOVES, {'i': it['id']}).data['stockMovements']
        self.assertEqual([(m['type'], m['qty'], m['notes']) for m in mv], [('in', 20.0, 'Opening stock')])

    def test_edit_cannot_change_stock_and_validates(self):
        it = self.make_item()
        r = gql(self.owner, SAVE, {'i': item_in(id=it['id'], name='Starter (renamed)', openingQty=999, minStockLevel=8, expiryDate='2027-01-31')})
        self.assertIsNone(r.errors, r.errors)
        got = r.data['saveStockItem']['item']
        self.assertEqual((got['name'], got['minStockLevel'], got['expiryDate'], got['currentQty']), ('Starter (renamed)', 8.0, '2027-01-31', 20.0))
        for bad in (item_in(name='  '), item_in(category='gold'), item_in(minStockLevel=-1), item_in(openingQty=-5), item_in(costPerUnit=-2)):
            self.assertTrue(gql(self.owner, SAVE, {'i': bad}).errors, bad)

    # ── movements ─────────────────────────────────────────────────────────
    def test_movements_change_stock_and_are_listed(self):
        it = self.make_item()
        d = '2026-10-01'
        r = gql(self.owner, MOVE, {'i': it['id'], 't': 'in', 'q': 10, 'd': d, 'r': 'PO-7', 'c': 360})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['recordStockMovement']['item']['currentQty'], 30.0)
        self.assertEqual(r.data['recordStockMovement']['movement']['date'], d)
        gql(self.owner, MOVE, {'i': it['id'], 't': 'out', 'q': 12, 'n': 'fed to batch 2'})
        gql(self.owner, MOVE, {'i': it['id'], 't': 'adjustment', 'q': -3, 'n': 'spillage'})        # a count correction can go down
        gql(self.owner, MOVE, {'i': it['id'], 't': 'adjustment', 'q': 1})
        r = gql(self.owner, MOVE, {'i': it['id'], 't': 'transfer', 'q': 2, 'dest': 'Store B'})
        self.assertEqual(r.data['recordStockMovement']['movement']['destination'], 'Store B')
        self.assertEqual(self.stock(it['id']), 14.0)                                              # 20 + 10 - 12 - 3 + 1 - 2
        kinds = [(m['type'], m['qty']) for m in gql(self.owner, MOVES, {'i': it['id']}).data['stockMovements']]
        self.assertEqual(kinds, [('transfer', 2.0), ('adjustment', 1.0), ('adjustment', -3.0), ('out', 12.0), ('in', 10.0), ('in', 20.0)])

    def test_people_cannot_take_out_more_than_is_there(self):
        it = self.make_item()                                                                      # 20 in stock
        r = gql(self.owner, MOVE, {'i': it['id'], 't': 'out', 'q': 25})
        self.assertIn('Only 20', str(r.errors))
        self.assertTrue(gql(self.owner, MOVE, {'i': it['id'], 't': 'adjustment', 'q': -25}).errors)
        self.assertTrue(gql(self.owner, MOVE, {'i': it['id'], 't': 'transfer', 'q': 25, 'dest': 'B'}).errors)
        self.assertEqual(self.stock(it['id']), 20.0)
        self.assertEqual(InventoryTransaction.objects.count(), 1)                                  # only the opening stock

    def test_movement_validation(self):
        it = self.make_item()
        for bad in ({'t': 'in', 'q': 0}, {'t': 'in', 'q': -4}, {'t': 'adjustment', 'q': 0}, {'t': 'swap', 'q': 1},
                    {'t': 'transfer', 'q': 1}, {'t': 'transfer', 'q': 1, 'dest': '  '}):
            self.assertTrue(gql(self.owner, MOVE, dict({'i': it['id']}, **bad)).errors, bad)
        self.assertTrue(gql(self.owner, MOVE, {'i': 'not-a-uuid', 't': 'in', 'q': 1}).errors)

    # ── automatic postings ────────────────────────────────────────────────
    def test_goods_in_create_the_item_then_add_to_it(self):
        r = gql(self.owner, POST, {'s': 'production', 'items': [auto('prod:e1:harvest', name='Fresh Eggs', qty=300, unit='count')]})
        self.assertEqual(r.data['postStock'], {'created': 1, 'duplicates': 0, 'unmatched': 0, 'rejected': 0})
        egg = InventoryItem.objects.get(name='Fresh Eggs')
        self.assertEqual((egg.category, egg.unit, float(egg.current_stock), egg.sku), ('produce', 'count', 300.0, 'fresh-eggs'))
        gql(self.owner, POST, {'s': 'production', 'items': [auto('prod:e2:harvest', name='fresh  EGGS', qty=60, unit='count')]})   # matches regardless of case and spacing
        self.assertEqual(InventoryItem.objects.filter(name__icontains='eggs').count(), 1)
        self.assertEqual(float(InventoryItem.objects.get(name='Fresh Eggs').current_stock), 360.0)

    def test_postings_are_idempotent(self):
        items = [auto('k1', name='Honey', qty=12, unit='kg'), auto('k2', name='Honey', qty=3, unit='kg', direction='out')]
        r = gql(self.owner, POST, {'s': 'production', 'items': items}).data['postStock']
        self.assertEqual((r['created'], r['duplicates']), (2, 0))
        r = gql(self.owner, POST, {'s': 'production', 'items': items}).data['postStock']
        self.assertEqual((r['created'], r['duplicates']), (0, 2))
        self.assertEqual(float(InventoryItem.objects.get(name='Honey').current_stock), 9.0)

    def test_automatic_goods_out_never_fail_and_never_go_below_zero(self):
        it = self.make_item(openingQty=4)
        r = gql(self.owner, POST, {'s': 'sales', 'items': [auto('s1', direction='out', qty=10)]}).data['postStock']
        self.assertEqual(r['created'], 1)
        self.assertEqual(self.stock(it['id']), 0.0)
        mv = InventoryTransaction.objects.get(source_ref='s1')
        self.assertEqual(float(mv.quantity), 4.0)                                                  # what actually left
        self.assertIn('short by 6', mv.notes)
        r = gql(self.owner, POST, {'s': 'sales', 'items': [auto('s2', direction='out', qty=1)]}).data['postStock']
        self.assertEqual((r['created'], r['unmatched']), (0, 1))                                   # nothing left to take
        r = gql(self.owner, POST, {'s': 'sales', 'items': [auto('s3', name='Unknown Thing', direction='out')]}).data['postStock']
        self.assertEqual((r['created'], r['unmatched']), (0, 1))                                   # unknown item: ignored

    def test_bad_postings_are_rejected_not_fatal(self):
        items = [auto('a1', name='Maize bran', qty=5), auto('a2', qty=0), auto('a3', direction='sideways'), auto(''), auto('a5', name='  ')]
        r = gql(self.owner, POST, {'s': 'production', 'items': items}).data['postStock']
        self.assertEqual((r['created'], r['rejected']), (1, 4))

    def test_who_may_post_what(self):
        self.assertIsNone(gql(self.hand, POST, {'s': 'production', 'items': [auto('h1')]}).errors)      # farmhand logs production
        self.assertTrue(gql(self.hand, POST, {'s': 'sales', 'items': [auto('h2')]}).errors)
        self.assertTrue(gql(self.sales, POST, {'s': 'production', 'items': [auto('h3')]}).errors)
        self.assertTrue(gql(self.owner, POST, {'s': 'manual', 'items': [auto('h4')]}).errors)
        self.assertTrue(gql(self.hand, ITEMS).errors)                                                    # …but cannot read the stock

    # ── permissions & tenants ─────────────────────────────────────────────
    def test_permissions(self):
        it = self.make_item(user=self.prod)
        self.assertTrue(gql(self.sales, SAVE, {'i': item_in(name='x')}).errors)                          # view only
        self.assertEqual(len(gql(self.sales, ITEMS).data['stockItems']), 1)
        self.assertTrue(gql(self.sales, MOVE, {'i': it['id'], 't': 'in', 'q': 1}).errors)
        self.assertTrue(gql(self.prod, DEL, {'id': it['id']}).errors)                                    # production manager: no delete
        self.assertTrue(gql(AnonymousUser(), ITEMS).errors)
        self.assertIsNone(gql(self.owner, DEL, {'id': it['id']}).errors)
        self.assertEqual(InventoryTransaction.objects.count(), 0)                                        # history went with it

    def test_other_organisations_cannot_see_or_change_anything(self):
        it = self.make_item()
        self.assertEqual(gql(self.stranger, ITEMS).data['stockItems'], [])
        self.assertTrue(gql(self.stranger, MOVE, {'i': it['id'], 't': 'in', 'q': 5}).errors)
        self.assertTrue(gql(self.stranger, SAVE, {'i': item_in(id=it['id'], name='hijack')}).errors)
        self.assertTrue(gql(self.stranger, DEL, {'id': it['id']}).errors)
        self.assertTrue(gql(self.stranger, MOVES, {'i': it['id']}).errors)
        gql(self.stranger, POST, {'s': 'production', 'items': [auto('same-key')]})
        r = gql(self.owner, POST, {'s': 'production', 'items': [auto('same-key')]}).data['postStock']
        self.assertEqual(r['created'], 1)                                                                # keys are per company
        self.assertEqual(InventoryItem.objects.get(pk=it['id']).name, 'Broiler Starter Feed')

    # ── sales link ────────────────────────────────────────────────────────
    def test_fulfilling_a_sale_takes_the_goods_out_of_stock(self):
        feed = self.make_item(name='Broilers (live)', unit='head', openingQty=100)
        order = gql(self.owner, NEW_ORDER, {'i': {'newCustomerName': 'Butchery', 'date': date.today().isoformat(),
                    'lines': [{'description': 'Broilers (live)', 'qty': 30, 'unit': 'head', 'unitPrice': 90},
                              {'description': 'Something we do not stock', 'qty': 2, 'unit': 'kg', 'unitPrice': 10}]}}).data['createSaleOrder']['order']
        gql(self.owner, UPD, {'id': order['id'], 's': 'confirmed'})
        self.assertEqual(self.stock(feed['id']), 100.0)                                                  # nothing until fulfilled
        r = gql(self.owner, UPD, {'id': order['id'], 's': 'fulfilled'})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(self.stock(feed['id']), 70.0)
        mv = InventoryTransaction.objects.get(item_id=feed['id'], source='sales')
        self.assertIn(order['id'], mv.source_ref)
        self.assertEqual(mv.destination, 'Butchery')
        gql(self.owner, UPD, {'id': order['id'], 's': 'fulfilled'})                                      # asking again changes nothing
        self.assertEqual(self.stock(feed['id']), 70.0)

    def test_a_sale_larger_than_stock_still_completes(self):
        feed = self.make_item(name='Eggs', unit='tray', openingQty=3)
        order = gql(self.owner, NEW_ORDER, {'i': {'newCustomerName': 'Cafe', 'date': date.today().isoformat(),
                    'lines': [{'description': 'Eggs', 'qty': 10, 'unit': 'tray', 'unitPrice': 60}]}}).data['createSaleOrder']['order']
        gql(self.owner, UPD, {'id': order['id'], 's': 'confirmed'})
        r = gql(self.owner, UPD, {'id': order['id'], 's': 'fulfilled'})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['updateSaleOrder']['order']['status'], 'fulfilled')
        self.assertEqual(self.stock(feed['id']), 0.0)

    # ── legacy import ─────────────────────────────────────────────────────
    def legacy(self):
        items = [{'legacyId': 'i1', 'name': 'Maize Seed', 'category': 'seed', 'unit': 'kg', 'currentQty': 80, 'minStockLevel': 20, 'costPerUnit': 18.5, 'expiryDate': '2027-03-01'},
                 {'legacyId': 'i2', 'name': 'Vaccine', 'category': 'medicine', 'unit': 'dose', 'currentQty': 0}]
        moves = [{'legacyId': 'm1', 'legacyItemId': 'i1', 'type': 'in', 'qty': 100, 'date': '2026-09-01', 'reference': 'PO-1'},
                 {'legacyId': 'm2', 'legacyItemId': 'i1', 'type': 'out', 'qty': 20, 'date': '2026-09-10'},
                 {'legacyId': 'm3', 'legacyItemId': 'gone', 'type': 'in', 'qty': 5},                     # item unknown
                 {'legacyId': 'm4', 'legacyItemId': 'i1', 'type': 'swap', 'qty': 5}]                     # bad type
        return items, moves

    def test_legacy_import_keeps_levels_and_is_idempotent(self):
        items, moves = self.legacy()
        r = gql(self.owner, IMPORT, {'i': items, 'm': moves}).data['importStockData']
        self.assertEqual(r, {'itemsCreated': 2, 'movementsCreated': 2, 'skipped': 0, 'rejected': 2})
        seed = InventoryItem.objects.get(legacy_id='i1')
        self.assertEqual((float(seed.current_stock), float(seed.reorder_level), float(seed.unit_cost), str(seed.expiry_date)), (80.0, 20.0, 18.5, '2027-03-01'))
        hist = gql(self.owner, MOVES, {'i': str(seed.id)}).data['stockMovements']
        self.assertEqual({(m['type'], m['qty'], m['source']) for m in hist}, {('in', 100.0, 'import'), ('out', 20.0, 'import')})
        r = gql(self.owner, IMPORT, {'i': items, 'm': moves}).data['importStockData']
        self.assertEqual((r['itemsCreated'], r['movementsCreated'], r['skipped']), (0, 0, 4))
        self.assertEqual(float(InventoryItem.objects.get(pk=seed.pk).current_stock), 80.0)               # untouched

    def test_import_needs_inventory_create(self):
        items, moves = self.legacy()
        self.assertTrue(gql(self.hand, IMPORT, {'i': items, 'm': moves}).errors)
        self.assertTrue(gql(self.sales, IMPORT, {'i': items, 'm': moves}).errors)

    # ── helpers ───────────────────────────────────────────────────────────
    def test_matching_helpers(self):
        self.assertEqual(slug('Broilers (live)'), 'broilers-live')
        self.assertEqual(slug('  Layer  Mash '), 'layer-mash')
        self.assertEqual([infer_category(n) for n in ('Layer meal', 'Newcastle vaccine', 'Urea', 'Fresh milk', 'Egg trays', 'Water pump', 'Mystery')],
                         ['feed', 'medicine', 'fertiliser', 'produce', 'packaging', 'equipment', 'produce'])

"""Vendor operations — every vendor type runs its business through the vendor schema."""
import json
from datetime import date, timedelta

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import Organization, Profile
from apps.market.models import MarketListing
from apps.market.provider_models import Provider, HireBooking, VetAppointment, EquipmentCatalog, ProviderStaff
from apps.market.vendor_models import VendorInvoice, VendorOrder, WorkOrder, ProcessingBatch
from config.schema import schema


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


_n = [700]


def _vendor(name, bt, district='Chongwe'):
    _n[0] += 1
    org = Organization.objects.create(name=name, slug=f'v-{_n[0]}', org_type='farm', business_type=bt, province='Lusaka', district=district)
    u = Profile.objects.create_user(email=f'v{_n[0]}@t.test', full_name='V', password='pw12345678', phone=f'097{_n[0]:08d}', organization=org, role='director', is_org_admin=True)
    return org, u


class VendorTest(TestCase):
    def setUp(self):
        self.vet_org, self.vet = _vendor('Chongwe Vet Clinic', 'vet_provider')
        self.eq_org, self.eq = _vendor('Kafue Tractors', 'equipment_hire', 'Kafue')
        self.dealer_org, self.dealer = _vendor('Agro Inputs Ltd', 'agro_dealer')
        self.svc_org, self.svc = _vendor('Irrigation Pros', 'agriservices_provider')
        self.proc_org, self.proc = _vendor('Lusaka Millers', 'processor', 'Lusaka')
        self.tr_org, self.tr = _vendor('Zambezi Haulage', 'transport')
        self.farm_org, self.farmer = _vendor('Green Acres', 'farmer')

    # ── profile ──────────────────────────────────────────────────────────────
    def test_ensure_my_provider_maps_business_type(self):
        for user, ptype in ((self.vet, 'vet_services'), (self.eq, 'equipment_hire'), (self.dealer, 'agro_dealer'), (self.svc, 'agri_services'), (self.proc, 'processing'), (self.tr, 'transport')):
            r = _gql(user, 'mutation { ensureMyProvider { created provider { id name providerType status district } } }')
            self.assertIsNone(r.errors, r.errors)
            pr = r.data['ensureMyProvider']['provider']
            self.assertTrue(r.data['ensureMyProvider']['created'])
            self.assertEqual(pr['providerType'].lower(), ptype)
            self.assertEqual(pr['status'].lower(), 'active')
            self.assertEqual(pr['name'], user.organization.name)
        # idempotent
        r = _gql(self.vet, 'mutation { ensureMyProvider { created provider { id } } }')
        self.assertFalse(r.data['ensureMyProvider']['created'])
        self.assertEqual(Provider.objects.filter(registered_by=self.vet_org).count(), 1)
        self.assertTrue(_gql(None, 'mutation { ensureMyProvider { created } }').errors)
        # update profile + staff + services + certifications
        r = _gql(self.vet, '''mutation { updateMyProvider(input: { tagline: "Farm-gate animal health", mobileService: true, coverageDistricts: ["Chongwe", "Kafue"], serviceHours: "Mon-Sat 08:00-17:00" }) { provider { tagline mobileService coverageDistricts } }
            s1: upsertStaff(input: { name: "Dr N. Hamoonga", role: "vet_officer", licenceNo: "VRAZ-1234" }) { staff { id name role } }
            sv: upsertService(input: { name: "Farm visit consultation", pricingModel: "per_head", price: 25, unitLabel: "per animal", category: "Consultation" }) { service { id name price } }
            c: upsertCertification(input: { name: "VRAZ registration", issuingBody: "VRAZ", expiryDate: "2020-01-01" }) { certification { id status } } }''')
        self.assertIsNone(r.errors, r.errors)
        self.assertTrue(r.data['updateMyProvider']['provider']['mobileService'])
        self.assertEqual(r.data['c']['certification']['status'].lower(), 'expired')  # past expiry auto-flagged
        # other vendors cannot edit my staff
        sid = r.data['s1']['staff']['id']
        self.assertTrue(_gql(self.eq, 'mutation($id: UUID!) { deleteStaff(id: $id) { ok } }', {'id': sid}).errors)
        self.assertIsNone(_gql(self.vet, 'mutation($id: UUID!) { deleteStaff(id: $id) { ok } }', {'id': sid}).errors)

    # ── vet ──────────────────────────────────────────────────────────────────
    def test_vet_appointments_end_to_end(self):
        _gql(self.vet, 'mutation { ensureMyProvider { created } }')
        p = Provider.objects.get(registered_by=self.vet_org)
        officer = ProviderStaff.objects.create(provider=p, name='Dr H', role='vet_officer')
        # farmer books through the marketplace
        r = _gql(self.farmer, 'mutation($pid: UUID!) { bookVetAppointment(input: { providerId: $pid, apptType: "vaccination", apptDate: "2026-09-20", species: "Cattle", animalCount: 40, symptoms: "FMD booster due" }) { ok appointment { id apptRef } } }', {'pid': str(p.id)})
        self.assertIsNone(r.errors, r.errors)
        aid = r.data['bookVetAppointment']['appointment']['id']
        # practice sees it (farmer's own list is separate); other vendor does not
        r = _gql(self.vet, 'query { providerVetAppointments { id status organization { name } species } vendorSummary { upcomingAppointments } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(len(r.data['providerVetAppointments']), 1)
        self.assertEqual(r.data['providerVetAppointments'][0]['organization']['name'], 'Green Acres')
        self.assertTrue(_gql(self.eq, 'query { providerVetAppointments { id } }').errors)  # no provider profile yet -> error, never someone else's data
        # walk-in appointment created by the practice
        r = _gql(self.vet, 'mutation($o: UUID!) { createProviderAppointment(input: { clientName: "Mr Banda (walk-in)", clientPhone: "0977000111", apptType: "treatment", apptDate: "2026-09-12", species: "Goats", animalCount: 12, vetOfficerId: $o, consultationFee: 300 }) { appointment { id apptRef clientName status } } }', {'o': str(officer.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['createProviderAppointment']['appointment']['clientName'], 'Mr Banda (walk-in)')
        # outcome with prescription, follow-up and billing
        r = _gql(self.vet, '''mutation($id: UUID!) { vendorUpdateVetAppointment(id: $id, input: { status: "completed", diagnosis: "Foot-and-mouth prophylaxis", treatmentGiven: "FMD vaccine 2 ml IM",
            medications: [{ name: "FMD vaccine (Aftovax)", dose: "2 ml", route: "IM", days: 1, withdrawalDays: 0 }, { name: "Multivitamin", dose: "10 ml", route: "SC", days: 1 }],
            followUpDate: "2027-03-20", totalAmount: 1200, paid: true }) { appointment { status diagnosis medications followUpDate totalAmount paid } } }''', {'id': aid})
        self.assertIsNone(r.errors, r.errors)
        a = r.data['vendorUpdateVetAppointment']['appointment']
        self.assertEqual(len(json.loads(a['medications'])), 2)
        self.assertTrue(a['paid'])
        # farmer cannot use the practice-side mutation
        self.assertTrue(_gql(self.farmer, 'mutation($id: UUID!) { vendorUpdateVetAppointment(id: $id, input: { diagnosis: "x" }) { appointment { id } } }', {'id': aid}).errors)
        # patients + prescriptions + revenue
        r = _gql(self.vet, 'query { vetPatients { clientName species animalCount visits conditions medications nextFollowUp } providerVetAppointments(withMedications: true) { id } vendorSummary { revenue30d revenueYtd clients revenueByKind } vendorClients { name interactions totalValue kinds } }')
        self.assertIsNone(r.errors, r.errors)
        pats = {x['clientName']: x for x in r.data['vetPatients']}
        self.assertEqual(pats['Green Acres']['animalCount'], 40)
        self.assertIn('Foot-and-mouth prophylaxis', pats['Green Acres']['conditions'])
        self.assertIn('FMD vaccine (Aftovax)', pats['Green Acres']['medications'])
        self.assertEqual(pats['Green Acres']['nextFollowUp'], '2027-03-20')
        self.assertEqual(len(r.data['providerVetAppointments']), 1)
        # revenue: the paid appointment is dated 2026-09-20 (future) -> not in last 30 days; ytd counts it
        self.assertEqual(r.data['vendorSummary']['revenueYtd'], 1200.0)
        self.assertEqual(json.loads(r.data['vendorSummary']['revenueByKind']), {'vet': 1200.0})
        self.assertEqual(r.data['vendorSummary']['clients'], 2)
        names = {c['name']: c for c in r.data['vendorClients']}
        self.assertEqual(names['Green Acres']['totalValue'], 1200.0)
        self.assertEqual(names['Mr Banda (walk-in)']['kinds'], ['vet'])

    # ── equipment hire ───────────────────────────────────────────────────────
    def test_equipment_fleet_bookings_maintenance_invoice(self):
        _gql(self.eq, 'mutation { ensureMyProvider { created } }')
        p = Provider.objects.get(registered_by=self.eq_org)
        r = _gql(self.eq, 'mutation { upsertEquipment(input: { equipmentType: "tractor", name: "MF 385", make: "Massey Ferguson", capacity: "85 HP", dailyRate: 1500, perHaRate: 450 }) { equipment { id name isAvailable } } }')
        self.assertIsNone(r.errors, r.errors)
        eid = r.data['upsertEquipment']['equipment']['id']
        # farmer books; provider quotes, confirms, completes, invoices, gets paid
        r = _gql(self.farmer, 'mutation($pid: UUID!, $e: UUID!) { createHireBooking(input: { providerId: $pid, equipmentId: $e, startDate: "2026-10-01", endDate: "2026-10-03", hectares: 12 }) { booking { id bookingRef status } } }', {'pid': str(p.id), 'e': eid})
        self.assertIsNone(r.errors, r.errors)
        bid = r.data['createHireBooking']['booking']['id']
        bad = _gql(self.eq, 'mutation($id: UUID!) { vendorUpdateHireBooking(id: $id, input: { status: "quoted" }) { booking { id } } }', {'id': bid})
        self.assertTrue(bad.errors)  # quote needs an amount
        r = _gql(self.eq, 'mutation($id: UUID!) { vendorUpdateHireBooking(id: $id, input: { status: "quoted", quotedAmount: 5400, providerNotes: "Includes operator, excludes fuel" }) { booking { status quotedAmount } } }', {'id': bid})
        self.assertIsNone(r.errors, r.errors)
        r = _gql(self.eq, 'mutation($id: UUID!) { vendorUpdateHireBooking(id: $id, input: { status: "completed", agreedAmount: 5400 }) { booking { status } } }', {'id': bid})
        self.assertIsNone(r.errors, r.errors)
        # cannot delete equipment with active bookings? (completed is fine) -> mark a confirmed one
        r = _gql(self.eq, 'mutation($e: UUID!) { createProviderBooking(input: { clientName: "Walk-in farmer", equipmentId: $e, startDate: "2026-11-01", endDate: "2026-11-02", status: "confirmed", agreedAmount: 3000 }) { booking { id bookingRef clientName } } }', {'e': eid})
        self.assertIsNone(r.errors, r.errors)
        self.assertTrue(_gql(self.eq, 'mutation($e: UUID!) { deleteEquipment(id: $e) { ok } }', {'e': eid}).errors)
        # invoice from the booking, paid -> booking final_paid, revenue
        r = _gql(self.eq, 'mutation($b: UUID!) { upsertInvoice(input: { linkType: "hire", linkId: $b, tax: 0 }) { invoice { id invoiceRef total clientOrgName items status } } }', {'b': bid})
        self.assertIsNone(r.errors, r.errors)
        inv = r.data['upsertInvoice']['invoice']
        self.assertEqual((float(inv['total']), inv['clientOrgName']), (5400.0, 'Green Acres'))
        r = _gql(self.eq, 'mutation($i: UUID!) { setInvoiceStatus(id: $i, status: "paid", paymentMethod: "mobile_money") { invoice { status paidOn } } }', {'i': inv['id']})
        self.assertIsNone(r.errors, r.errors)
        self.assertTrue(HireBooking.objects.get(pk=bid).final_paid)
        # maintenance
        r = _gql(self.eq, 'mutation($e: UUID!) { addMaintenance(input: { equipmentId: $e, kind: "service", date: "2026-09-10", description: "500 h service", cost: 850, nextDueDate: "2026-09-20" }) { record { id equipmentName } } }', {'e': eid})
        self.assertIsNone(r.errors, r.errors)
        r = _gql(self.eq, 'query { vendorSummary { openBookings equipmentCount maintenanceDue revenueYtd revenueByKind } providerHireBookings { bookingRef status clientName organization { name } } vendorInvoices { invoiceRef status linkRef } }')
        self.assertIsNone(r.errors, r.errors)
        s = r.data['vendorSummary']
        self.assertEqual((s['openBookings'], s['equipmentCount'], s['maintenanceDue']), (1, 1, 1))
        self.assertEqual(s['revenueYtd'], 5400.0)  # invoice counted once, not the booking too
        self.assertEqual(len(r.data['providerHireBookings']), 2)
        self.assertEqual(r.data['vendorInvoices'][0]['linkRef'][:3], 'HB-')
        # farmer cannot see the provider's invoices
        self.assertTrue(_gql(self.farmer, 'query { vendorInvoices { id } }').errors)

    # ── dealer orders + listings + stock ─────────────────────────────────────
    def test_dealer_listings_orders_stock(self):
        _gql(self.dealer, 'mutation { ensureMyProvider { created } }')
        r = _gql(self.dealer, 'mutation { createListing(commodity: "Compound D fertiliser 50 kg", quantityAvailable: 100, askingPrice: 850, unit: "bag") { listing { id quantityAvailable status } } }')
        self.assertIsNone(r.errors, r.errors)
        lid = r.data['createListing']['listing']['id']
        r = _gql(self.dealer, 'mutation($l: UUID!) { upsertVendorOrder(input: { clientName: "Mrs Phiri", clientPhone: "0966111222", items: [{ listingId: $l, name: "Compound D 50 kg", quantity: 10, unit: "bag", unitPrice: 850 }], discount: 500 }) { order { id orderRef status subtotal total items } } }', {'l': lid})
        self.assertIsNone(r.errors, r.errors)
        o = r.data['upsertVendorOrder']['order']
        self.assertEqual((float(o['subtotal']), float(o['total'])), (8500.0, 8000.0))
        self.assertEqual(float(MarketListing.objects.get(pk=lid).quantity_available), 100.0)  # stock untouched while 'new'
        r = _gql(self.dealer, 'mutation($id: UUID!) { upsertVendorOrder(id: $id, input: { status: "confirmed" }) { order { status } } }', {'id': o['id']})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(float(MarketListing.objects.get(pk=lid).quantity_available), 90.0)  # decremented once
        r = _gql(self.dealer, 'mutation($id: UUID!) { upsertVendorOrder(id: $id, input: { status: "delivered", paid: true }) { order { status paid deliveredAt } } }', {'id': o['id']})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(float(MarketListing.objects.get(pk=lid).quantity_available), 90.0)  # not decremented again
        r = _gql(self.dealer, 'mutation($l: UUID!) { updateListing(id: $l, input: { quantityAvailable: 5, askingPrice: 900 }) { listing { quantityAvailable askingPrice } } }', {'l': lid})
        self.assertIsNone(r.errors, r.errors)
        r = _gql(self.dealer, 'query { vendorSummary { openOrders lowStock listingsActive revenue30d clients } vendorOrders { orderRef status total } vendorListings { commodity quantityAvailable } }')
        self.assertIsNone(r.errors, r.errors)
        s = r.data['vendorSummary']
        self.assertEqual((s['openOrders'], s['lowStock'], s['listingsActive'], s['revenue30d'], s['clients']), (0, 1, 1, 8000.0, 1))
        self.assertTrue(_gql(self.dealer, 'mutation($id: UUID!) { deleteVendorOrder(id: $id) { ok } }', {'id': o['id']}).errors)  # delivered orders stay

    # ── services + transport jobs ────────────────────────────────────────────
    def test_work_orders_for_services_and_transport(self):
        _gql(self.svc, 'mutation { ensureMyProvider { created } }')
        _gql(self.tr, 'mutation { ensureMyProvider { created } }')
        r = _gql(self.svc, 'mutation { sv: upsertService(input: { name: "Drip irrigation install", pricingModel: "per_ha", price: 12000 }) { service { id } } }')
        sid = r.data['sv']['service']['id']
        r = _gql(self.svc, 'mutation($s: UUID!, $c: ID!) { upsertWorkOrder(input: { clientOrgId: $c, serviceId: $s, kind: "installation", title: "Drip system, 2 ha block", scheduledDate: "2026-09-15", quantity: 2, unit: "ha", quotedAmount: 24000, status: "scheduled" }) { job { id jobRef status clientOrgName serviceName } } }', {'s': sid, 'c': str(self.farm_org.id)})
        self.assertIsNone(r.errors, r.errors)
        j = r.data['upsertWorkOrder']['job']
        self.assertEqual((j['clientOrgName'], j['serviceName'], j['status']), ('Green Acres', 'Drip irrigation install', 'scheduled'))
        r = _gql(self.svc, 'mutation($id: UUID!) { upsertWorkOrder(id: $id, input: { title: "Drip system, 2 ha block", status: "completed", agreedAmount: 24000, completionNotes: "Commissioned, farmer trained" }) { job { status completedAt paid } } }', {'id': j['id']})
        self.assertIsNone(r.errors, r.errors)
        self.assertIsNotNone(r.data['upsertWorkOrder']['job']['completedAt'])
        r = _gql(self.svc, 'mutation($j: UUID!) { upsertInvoice(input: { linkType: "job", linkId: $j }) { invoice { total items clientOrgName } } }', {'j': j['id']})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(float(r.data['upsertInvoice']['invoice']['total']), 24000.0)
        # transporter job with route
        r = _gql(self.tr, 'mutation { upsertWorkOrder(input: { clientName: "Chongwe Coop", kind: "transport", title: "Maize to FRA depot", location: "Chongwe", destination: "Lusaka FRA", distanceKm: 48, quantity: 30, unit: "tonnes", agreedAmount: 9000, status: "in_progress" }) { job { jobRef kind destination } } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['upsertWorkOrder']['job']['kind'], 'transport')
        r = _gql(self.tr, 'query { vendorSummary { openJobs } vendorWorkOrders(kind: "transport") { title } }')
        self.assertEqual((r.data['vendorSummary']['openJobs'], len(r.data['vendorWorkOrders'])), (1, 1))
        # the services provider cannot see the transporter's jobs
        self.assertEqual(len(_gql(self.svc, 'query { vendorWorkOrders { id } }').data['vendorWorkOrders']), 1)

    # ── processor batches / traceability ─────────────────────────────────────
    def test_processing_batches(self):
        _gql(self.proc, 'mutation { ensureMyProvider { created } }')
        r = _gql(self.proc, 'mutation($c: ID!) { upsertBatch(input: { sourceOrgId: $c, inputCommodity: "Maize grain", inputQuantity: 5000, inputUnit: "kg", pricePaid: 17500, receivedOn: "2026-09-01" }) { batch { id lotCode status sourceName sourceDistrict } } }', {'c': str(self.farm_org.id)})
        self.assertIsNone(r.errors, r.errors)
        b = r.data['upsertBatch']['batch']
        self.assertEqual((b['status'], b['sourceName'], b['sourceDistrict']), ('received', 'Green Acres', 'Chongwe'))
        r = _gql(self.proc, 'mutation($id: UUID!) { upsertBatch(id: $id, input: { inputCommodity: "Maize grain", inputQuantity: 5000, receivedOn: "2026-09-01", status: "completed", product: "Breakfast mealie meal 25 kg", outputQuantity: 160, outputUnit: "bags", qcPassed: true }) { batch { status yieldPct quantityRemaining completedOn startedOn } } }', {'id': b['id']})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['upsertBatch']['batch']['yieldPct'], 3.2)
        self.assertEqual(r.data['upsertBatch']['batch']['quantityRemaining'], 160.0)
        r = _gql(self.proc, 'query { vendorSummary { batchesInProcess finishedStock clients } vendorBatches { lotCode sourceOrgName } vendorClients { name kinds } }')
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual((r.data['vendorSummary']['batchesInProcess'], r.data['vendorSummary']['finishedStock']), (0, 160.0))
        self.assertEqual(r.data['vendorClients'][0]['kinds'], ['supplier'])
        self.assertTrue(_gql(self.proc, 'mutation { upsertBatch(input: { inputCommodity: "x", inputQuantity: 0, receivedOn: "2026-09-01" }) { batch { id } } }').errors)

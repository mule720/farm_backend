"""Export & trade document generation tests."""
import json
import os
from datetime import date

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
import tempfile

from apps.accounts.models import Organization, Profile
from apps.market.models import BuyerProfile, TradeContract, ExportDocument
from apps.market import documents
from config.schema import schema

TMP = tempfile.mkdtemp(prefix='agrinuxes_media_')


def _gql(user, query, variables=None):
    request = RequestFactory().post('/graphql/', data=json.dumps({'query': query}), content_type='application/json')
    request.user = user if user is not None else AnonymousUser()
    return schema.execute(query, variable_values=variables or {}, context_value=request)


@override_settings(MEDIA_ROOT=TMP, MEDIA_URL='/media/')
class ExportDocsTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Chongwe Green Acres', slug='cga-x', org_type='farm', province='Lusaka', district='Chongwe', country='Zambia')
        self.user = Profile.objects.create_user(email='d@cga.test', full_name='Director', password='pw12345678', phone='0977000111', organization=self.org, role='director')
        self.other_org = Organization.objects.create(name='Other', slug='other-x', org_type='farm')
        self.other = Profile.objects.create_user(email='o@other.test', full_name='O', password='pw12345678', phone='0977000222', organization=self.other_org, role='director')
        self.buyer = BuyerProfile.objects.create(organization=self.org, name='Harare Fresh Ltd', buyer_type='exporter', contact_person='T. Moyo',
                                                 phone='+263 77 000', address='12 Samora Machel Ave', town='Harare', country='Zimbabwe', payment_terms='50% deposit, balance on delivery')
        self.contract = TradeContract.objects.create(organization=self.org, buyer=self.buyer, commodity='Soya beans, Grade A', quantity_agreed=12000,
                                                     unit='kg', agreed_price=14.5, currency='ZMW', delivery_date=date(2026, 10, 15), deposit_pct=50, created_by=self.user)
        self.domestic_buyer = BuyerProfile.objects.create(organization=self.org, name='Shoprite Lusaka', buyer_type='supermarket', country='Zambia')
        self.domestic = TradeContract.objects.create(organization=self.org, buyer=self.domestic_buyer, commodity='Broiler chickens', quantity_agreed=500,
                                                     unit='birds', agreed_price=85, created_by=self.user)

    def _assert_pdf(self, url):
        self.assertTrue(url.startswith('/media/export_docs/'))
        path = os.path.join(TMP, 'export_docs', os.path.basename(url))
        self.assertTrue(os.path.exists(path), path)
        with open(path, 'rb') as f:
            head = f.read(5)
        self.assertEqual(head, b'%PDF-')
        self.assertGreater(os.path.getsize(path), 1500)

    def test_doc_numbering_sequential_per_type_and_org(self):
        self.assertEqual(documents.next_doc_number(self.org, 'invoice'), f'INV-{date.today().year}-0001')
        ExportDocument.objects.create(organization=self.org, doc_type='invoice', doc_number=f'INV-{date.today().year}-0007', commodity='x')
        self.assertEqual(documents.next_doc_number(self.org, 'invoice'), f'INV-{date.today().year}-0008')
        self.assertEqual(documents.next_doc_number(self.org, 'phytosanitary'), f'PHY-{date.today().year}-0001')
        self.assertEqual(documents.next_doc_number(self.other_org, 'invoice'), f'INV-{date.today().year}-0001')

    def test_every_doc_type_renders(self):
        for t, _ in ExportDocument.DOC_TYPE_CHOICES:
            d = ExportDocument.objects.create(organization=self.org, contract=self.contract, doc_type=t, commodity=self.contract.commodity,
                                              quantity=self.contract.quantity_agreed, unit='kg', destination_country='Zimbabwe', created_by=self.user)
            url = documents.build_export_document_pdf(d)
            self._assert_pdf(url)
            d.refresh_from_db()
            self.assertEqual(d.document_url, url)
            self.assertTrue(d.doc_number.startswith(documents.DOC_PREFIX[t]))
            if t in documents.DEFAULT_AUTHORITY:
                self.assertEqual(d.issuing_authority, documents.DEFAULT_AUTHORITY[t])

    def test_contract_pdf(self):
        self._assert_pdf(documents.build_contract_pdf(self.contract))

    def test_checklist_plant_export_vs_domestic_animal(self):
        q = 'query($id: UUID!) { exportChecklist(contractId: $id) { docType required document { id } } }'
        r = _gql(self.user, q, {'id': str(self.contract.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual([x['docType'] for x in r.data['exportChecklist']], ['invoice', 'packing_list', 'phytosanitary', 'coo', 'customs'])
        self.assertTrue(all(x['document'] is None for x in r.data['exportChecklist']))
        r = _gql(self.user, q, {'id': str(self.domestic.id)})
        self.assertEqual([x['docType'] for x in r.data['exportChecklist']], ['invoice', 'packing_list'])

    def test_create_prefills_from_contract_and_generates(self):
        m = 'mutation($input: ExportDocumentInput!) { createExportDocument(input: $input, generate: true) { document { id docNumber commodity quantity unit destinationCountry issuingAuthority documentUrl status } } }'
        r = _gql(self.user, m, {'input': {'contractId': str(self.contract.id), 'docType': 'phytosanitary', 'notes': 'Treated with phosphine 48h'}})
        self.assertIsNone(r.errors, r.errors)
        d = r.data['createExportDocument']['document']
        self.assertEqual(d['commodity'], 'Soya beans, Grade A')
        self.assertEqual(float(d['quantity']), 12000)
        self.assertEqual(d['destinationCountry'], 'Zimbabwe')
        self.assertEqual(d['docNumber'], f'PHY-{date.today().year}-0001')
        self.assertIn('Phytosanitary', d['issuingAuthority'])
        self._assert_pdf(d['documentUrl'])
        # checklist now shows it
        r = _gql(self.user, 'query($id: UUID!) { exportChecklist(contractId: $id) { docType document { docNumber } } }', {'id': str(self.contract.id)})
        by = {x['docType']: x for x in r.data['exportChecklist']}
        self.assertEqual(by['phytosanitary']['document']['docNumber'], d['docNumber'])

    def test_generate_export_pack_is_idempotent(self):
        m = 'mutation($id: UUID!) { generateExportPack(contractId: $id) { created documents { docType docNumber documentUrl } } }'
        r = _gql(self.user, m, {'id': str(self.contract.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['generateExportPack']['created'], 5)
        for d in r.data['generateExportPack']['documents']:
            self._assert_pdf(d['documentUrl'])
        r = _gql(self.user, m, {'id': str(self.contract.id)})
        self.assertEqual(r.data['generateExportPack']['created'], 0)
        self.assertEqual(ExportDocument.objects.filter(contract=self.contract).count(), 5)

    def test_update_status_and_dates_regenerates(self):
        d = ExportDocument.objects.create(organization=self.org, contract=self.contract, doc_type='coo', commodity='Soya', quantity=1, unit='t')
        m = 'mutation($id: UUID!, $input: ExportDocumentInput!) { updateExportDocument(id: $id, input: $input, regenerate: true) { document { status issueDate documentUrl quantity } } }'
        r = _gql(self.user, m, {'id': str(d.id), 'input': {'status': 'approved', 'issueDate': '2026-09-10', 'expiryDate': '2026-12-10', 'quantity': 12000.0}})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['updateExportDocument']['document']['status'], 'approved')
        self.assertEqual(float(r.data['updateExportDocument']['document']['quantity']), 12000.0)
        self._assert_pdf(r.data['updateExportDocument']['document']['documentUrl'])
        r = _gql(self.user, m, {'id': str(d.id), 'input': {'issueDate': '2026-09-10', 'expiryDate': '2026-01-01'}})
        self.assertTrue('Expiry' in str(r.errors[0]))
        r = _gql(self.user, m, {'id': str(d.id), 'input': {'status': 'bogus'}})
        self.assertTrue(r.errors)

    def test_org_scoping(self):
        d = ExportDocument.objects.create(organization=self.org, contract=self.contract, doc_type='invoice', commodity='Soya', quantity=1)
        self.assertTrue(_gql(self.other, 'mutation($id: UUID!) { generateExportDocumentPdf(id: $id) { url } }', {'id': str(d.id)}).errors)
        self.assertTrue(_gql(self.other, 'mutation($id: UUID!) { generateContractPdf(id: $id) { url } }', {'id': str(self.contract.id)}).errors)
        self.assertTrue(_gql(self.other, 'mutation($id: UUID!) { generateExportPack(contractId: $id) { created } }', {'id': str(self.contract.id)}).errors)
        self.assertEqual(_gql(self.other, 'query { exportDocuments { id } }').data['exportDocuments'], [])
        self.assertTrue(_gql(None, 'query { exportDocuments { id } }').errors)
        m = 'mutation($input: ExportDocumentInput!) { createExportDocument(input: $input) { document { id } } }'
        self.assertTrue(_gql(self.other, m, {'input': {'contractId': str(self.contract.id), 'docType': 'invoice'}}).errors)

    def test_update_trade_contract_and_contract_pdf_mutation(self):
        m = 'mutation($id: UUID!) { updateTradeContract(id: $id, deliveryAddress: "Beitbridge border, Zimbabwe", paymentTerms: "LC at sight", agreedPrice: 15.25) { contract { deliveryAddress paymentTerms agreedPrice totalValue } } }'
        r = _gql(self.user, m, {'id': str(self.contract.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(r.data['updateTradeContract']['contract']['paymentTerms'], 'LC at sight')
        self.assertEqual(float(r.data['updateTradeContract']['contract']['agreedPrice']), 15.25)
        self.assertEqual(float(r.data['updateTradeContract']['contract']['totalValue']), 12000 * 15.25)
        r = _gql(self.user, 'mutation($id: UUID!) { updateContractStatus(id: $id, status: "in_progress", quantityDelivered: 4000.5) { contract { status quantityDelivered } } }', {'id': str(self.contract.id)})
        self.assertIsNone(r.errors, r.errors)
        self.assertEqual(float(r.data['updateContractStatus']['contract']['quantityDelivered']), 4000.5)
        r = _gql(self.user, 'mutation($id: UUID!) { generateContractPdf(id: $id) { url } }', {'id': str(self.contract.id)})
        self.assertIsNone(r.errors, r.errors)
        self._assert_pdf(r.data['generateContractPdf']['url'])

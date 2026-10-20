from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from django.contrib.auth import get_user_model
from apps.accounts.models import Organization

User = get_user_model()
from . import catalog, knowledge, service


class KnowledgeTests(TestCase):
    def test_guide_is_indexed(self):
        self.assertGreater(len(knowledge._index()['chunks']), 500)

    def test_template_question_finds_the_templates_part(self):
        hits = knowledge.search('how do I save my own template with my feed brand', 'farmer')
        self.assertTrue(hits)
        self.assertIn('Part 2', hits[0]['title'])

    def test_vendor_audience_boost(self):
        hits = knowledge.search('add a product to my catalogue', 'agro_dealer')
        self.assertTrue(hits)
        self.assertTrue(any('Agro Dealer' in h['title'] or 'Part 7' in h['title'] for h in hits))


class ServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        org = Organization.objects.create(name='Test Farm', slug='test-farm')
        self.user = User.objects.create_user(email='a@b.test', password='x', full_name='A B', organization=org)

    def _ask(self, q, **ctx):
        with mock.patch.object(service, 'available', return_value=False):
            return service.ask(self.user, '1.1.1.1', q, context=ctx)

    def test_vague_question_asks_back_with_choices(self):
        r = self._ask('help', accountType='farmer')
        self.assertTrue(r['testMode'])
        self.assertIn('What would you like to do', r['answer'])
        self.assertGreaterEqual(len(r['suggestions']), 3)

    def test_setup_intent_offers_add_enterprise_action(self):
        r = self._ask('I want to set up broiler chickens', accountType='farmer')
        self.assertEqual(r['actions'][0]['type'], 'add_enterprise')
        self.assertEqual(r['actions'][0]['templateId'], 'broiler_chicken')

    def test_navigation_request(self):
        r = self._ask('take me to inventory', accountType='farmer')
        self.assertEqual(r['actions'], [{'type': 'navigate', 'page': 'inventory', 'label': 'Open Inventory'}])

    def test_vendor_cannot_add_enterprise(self):
        r = self._ask('set up broiler chickens', accountType='agro_dealer')
        self.assertFalse([a for a in r['actions'] if a['type'] == 'add_enterprise'])

    def test_how_to_question_uses_the_guide(self):
        r = self._ask('how do I import daily records from a spreadsheet csv', accountType='farmer')
        self.assertTrue(r['sources'])
        self.assertIn('guide says', r['answer'])

    def test_model_actions_are_validated(self):
        raw = '{"answer":"ok","suggestions":["a"],"actions":[{"type":"navigate","page":"inventory"},{"type":"navigate","page":"../../etc"},{"type":"add_enterprise","templateId":"nope"}]}'
        with mock.patch.object(service, 'available', return_value=True), mock.patch.object(service, '_ask_model', return_value=raw):
            r = service.ask(self.user, '1.1.1.1', 'where do I see stock', context={'accountType': 'farmer'})
        self.assertFalse(r['testMode'])
        self.assertEqual([a['page'] for a in r['actions']], ['inventory'])

    def test_model_failure_falls_back_to_guide_mode(self):
        with mock.patch.object(service, 'available', return_value=True), mock.patch.object(service, '_ask_model', side_effect=RuntimeError('boom')):
            r = service.ask(self.user, '1.1.1.1', 'how do I record a daily log', context={'accountType': 'farmer'})
        self.assertTrue(r['testMode'])
        self.assertTrue(r['answer'])

    def test_daily_limit(self):
        with mock.patch.object(service, 'DAILY_LIMIT', 2):
            self._ask('how do I add stock', accountType='farmer')
            self._ask('how do I add stock', accountType='farmer')
            r = self._ask('how do I add stock', accountType='farmer')
        self.assertTrue(r['limited'])

    def test_visitor_is_treated_as_visitor(self):
        with mock.patch.object(service, 'available', return_value=False):
            r = service.ask(None, '9.9.9.9', 'which account should I register', context={'accountType': 'government'})
        self.assertTrue(r['answer'])
        self.assertEqual(catalog.account_type('nonsense'), 'farmer')


class GraphqlTests(TestCase):
    def test_anonymous_can_ask_and_status_reports_mode(self):
        cache.clear()
        from graphene.test import Client
        from config.schema import schema
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        req = RequestFactory().post('/graphql/')
        req.user = AnonymousUser()
        c = Client(schema)
        with mock.patch.object(service, 'available', return_value=False):
            out = c.execute('mutation { askAssistant(question: "Which account should I register?") { result } }', context_value=req)
        self.assertNotIn('errors', out)
        self.assertIn('answer', out['data']['askAssistant']['result'])
        out = c.execute('{ assistantStatus }', context_value=req)
        self.assertNotIn('errors', out)


class KeyFromAdminTests(TestCase):
    def test_key_saved_in_admin_store_turns_the_model_on(self):
        import os
        from apps.integration_settings.models import IntegrationCredential
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            self.assertFalse(service.available())
            row = IntegrationCredential(service='ai', is_active=True)
            row.set_api_key('sk-ant-test-1234')
            row.save()
            self.assertTrue(service.available())
            self.assertNotIn('sk-ant', row.encrypted_api_key)
            row.is_active = False
            row.save()
            self.assertFalse(service.available())

    @override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                                 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
    def test_admin_page_saves_key_encrypted_and_never_shows_it(self):
        from django.test import Client
        from apps.integration_settings.models import IntegrationCredential
        admin_user = User.objects.create_superuser(email='boss@x.test', password='pw12345!', full_name='Boss')
        c = Client()
        c.force_login(admin_user)
        r = c.post('/admin/integration_settings/integrationcredential/add/', {
            'service': 'ai', 'is_active': 'on', 'new_api_key': 'sk-ant-secret-9999', 'base_url': '', 'app_id': ''}, HTTP_HOST='localhost')
        self.assertEqual(r.status_code, 302)
        row = IntegrationCredential.objects.get(service='ai')
        self.assertEqual(row.get_api_key(), 'sk-ant-secret-9999')
        page = c.get(f'/admin/integration_settings/integrationcredential/{row.id}/change/', HTTP_HOST='localhost')
        self.assertNotIn(b'sk-ant-secret-9999', page.content)

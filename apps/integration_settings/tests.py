"""
Tests for Farming's (AgroNexus) admin-managed integration credentials —
the same feature already shipped in E-commerce, ERP, Shipping, Bus, and
Tourism. This app currently has no existing outbound client of its own to
wire (unlike the other five), so these tests cover the model, the
mutation's admin gate, and the resolver's fallback behavior — the
foundation any future payvault/notif_client integration will build on.
"""
from django.test import Client, TestCase

from apps.accounts.models import Profile
from config.schema import schema
from .models import IntegrationCredential
from .resolve import get_service_config


class FakeContext:
    def __init__(self, user):
        self.user = user


SAVE_MUTATION = '''
  mutation($service: String!, $baseUrl: String, $appId: String, $apiKey: String, $secret: String) {
    saveIntegrationCredential(service: $service, baseUrl: $baseUrl, appId: $appId, apiKey: $apiKey, secret: $secret) {
      ok error
      credential { service baseUrl appId maskedApiKey maskedSecret hasApiKey hasSecret isActive }
    }
  }
'''

LIST_QUERY = '{ integrationCredentials { service baseUrl maskedApiKey hasApiKey } }'


class IntegrationCredentialModelTest(TestCase):
    def test_api_key_round_trips_through_encryption(self):
        row = IntegrationCredential(service=IntegrationCredential.Service.PAYMENT)
        row.set_api_key('psy_test_abc123')
        self.assertNotEqual(row.encrypted_api_key, 'psy_test_abc123')
        self.assertEqual(row.get_api_key(), 'psy_test_abc123')

    def test_masked_shows_only_last_four(self):
        self.assertEqual(IntegrationCredential.masked('psy_test_abcdef123456'), '••••3456')
        self.assertEqual(IntegrationCredential.masked(''), '')


class SaveIntegrationCredentialMutationTest(TestCase):
    def setUp(self):
        self.admin = Profile.objects.create_user(email='admin1@example.com', full_name='Admin One', password='x', is_staff=True)
        self.regular = Profile.objects.create_user(email='reg1@example.com', full_name='Reg One', password='x', is_staff=False)

    def _gql(self, query, variables=None, user=None):
        return schema.execute(query, variables=variables or {}, context_value=FakeContext(user or self.admin))

    def test_non_admin_cannot_save_credentials(self):
        result = self._gql(SAVE_MUTATION, {
            'service': 'payment', 'baseUrl': 'https://payments.example.com', 'apiKey': 'secret123',
        }, user=self.regular)
        self.assertIsNone(result.errors, result.errors)
        self.assertFalse(result.data['saveIntegrationCredential']['ok'])
        self.assertEqual(IntegrationCredential.objects.count(), 0)

    def test_admin_can_save_and_key_is_never_returned_plaintext(self):
        result = self._gql(SAVE_MUTATION, {
            'service': 'payment', 'baseUrl': 'https://payments.example.com',
            'appId': 'APP-FARMING-1234', 'apiKey': 'psy_test_supersecret9999',
        })
        self.assertIsNone(result.errors, result.errors)
        payload = result.data['saveIntegrationCredential']
        self.assertTrue(payload['ok'])
        cred = payload['credential']
        self.assertEqual(cred['baseUrl'], 'https://payments.example.com')
        self.assertTrue(cred['hasApiKey'])
        self.assertEqual(cred['maskedApiKey'], '••••9999')
        self.assertNotIn('supersecret9999', str(result.data))

        row = IntegrationCredential.objects.get(service='payment')
        self.assertEqual(row.get_api_key(), 'psy_test_supersecret9999')

    def test_resaving_without_api_key_leaves_existing_key_untouched(self):
        self._gql(SAVE_MUTATION, {'service': 'payment', 'apiKey': 'psy_test_original'})
        self._gql(SAVE_MUTATION, {'service': 'payment', 'baseUrl': 'https://new-url.example.com'})
        row = IntegrationCredential.objects.get(service='payment')
        self.assertEqual(row.base_url, 'https://new-url.example.com')
        self.assertEqual(row.get_api_key(), 'psy_test_original')

    def test_invalid_service_rejected(self):
        result = self._gql(SAVE_MUTATION, {'service': 'not-a-real-service', 'apiKey': 'x'})
        self.assertIsNone(result.errors, result.errors)
        payload = result.data['saveIntegrationCredential']
        self.assertFalse(payload['ok'])
        self.assertIn('must be one of', payload['error'])

    def test_non_admin_gets_empty_list(self):
        IntegrationCredential.objects.create(service='payment', base_url='https://x.example.com')
        result = self._gql(LIST_QUERY, user=self.regular)
        self.assertIsNone(result.errors, result.errors)
        self.assertEqual(result.data['integrationCredentials'], [])


class ClientResolutionOrderTest(TestCase):
    def test_get_service_config_prefers_active_db_row(self):
        row = IntegrationCredential.objects.create(
            service='payment', base_url='https://from-admin-ui.example.com', app_id='APP-123',
        )
        row.set_secret('shared-secret-from-admin-ui')
        row.save()
        cfg = get_service_config('payment', defaults={'base_url': 'https://env-default.example.com'})
        self.assertEqual(cfg['base_url'], 'https://from-admin-ui.example.com')
        self.assertEqual(cfg['secret'], 'shared-secret-from-admin-ui')

    def test_inactive_row_is_ignored(self):
        IntegrationCredential.objects.create(
            service='payment', base_url='https://should-not-be-used.example.com', is_active=False,
        )
        cfg = get_service_config('payment', defaults={'base_url': 'https://env-default.example.com'})
        self.assertEqual(cfg['base_url'], 'https://env-default.example.com')

    def test_no_row_falls_back_to_defaults(self):
        cfg = get_service_config('payment', defaults={'base_url': 'https://env-default.example.com', 'api_key': 'env-key'})
        self.assertEqual(cfg['base_url'], 'https://env-default.example.com')
        self.assertEqual(cfg['api_key'], 'env-key')

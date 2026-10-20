from django.test import TestCase

from . import service


class ActionSpellingTests(TestCase):
    def test_sloppy_actions_are_still_understood(self):
        ctx = {'accountType': 'farmer', 'enterprises': [{'name': 'x', 'templateId': 'indigenous-chicken', 'baseTemplateId': 'indigenous-chicken'}]}
        acts = [
            {'type': 'start_cycle', 'variant': 'Breeder Flock', 'name': 'Village Layers'},
            {'type': 'startCycle', 'template_id': 'Indigenous / Village Chicken', 'cycleType': 'Egg Incubation & Hatch'},
            {'type': 'start_cycle', 'templateId': 'indigenous-chicken', 'variantId': 'layer-from-chicks'},
            {'type': 'start_cycle', 'templateId': 'indigenous-chicken', 'variantId': 'Broiler Grow-Out'},
        ]
        out = service._clean_actions(acts, 'farmer', ctx)
        self.assertEqual([a['variantId'] for a in out], ['breeder_flock', 'incubation', 'layer_from_chicks', 'broiler_grow_out'])
        self.assertTrue(all(a['templateId'] == 'indigenous-chicken' for a in out))


class LegacyKeyTests(TestCase):
    def test_values_saved_with_the_dev_key_still_decrypt_after_a_real_key_is_set(self):
        from django.test import override_settings
        from apps.integration_settings import crypto
        old = crypto.aes_encrypt('sk-ant-legacy-value-123456')          # dev fallback key (none configured in tests)
        with override_settings(INTEGRATION_CREDENTIAL_MASTER_KEY_HEX='11' * 32):
            self.assertEqual(crypto.aes_decrypt(old), 'sk-ant-legacy-value-123456')
            fresh = crypto.aes_encrypt('sk-ant-new-value-123456')
            self.assertEqual(crypto.aes_decrypt(fresh), 'sk-ant-new-value-123456')
        self.assertNotEqual(old[:16], fresh[:16])

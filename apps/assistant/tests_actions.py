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

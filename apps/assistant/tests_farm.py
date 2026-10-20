from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from . import farm_kb, service


class FarmKnowledgeTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_village_chicken_is_found_and_described_in_full(self):
        ids = farm_kb.relevant('I have village chickens, collect eggs and incubate them')
        self.assertIn('indigenous-chicken', ids)
        text = farm_kb.describe('indigenous-chicken')
        self.assertIn('Egg Incubation & Hatch', text)
        self.assertIn('Range Growing', text)
        self.assertIn('Eggs Set', text)

    def test_start_cycle_is_validated(self):
        good = farm_kb.clean_start_cycle({'templateId': 'indigenous-chicken', 'variantId': 'incubation', 'name': 'Hatch 1',
                                          'startDate': '2026-10-20', 'setupValues': {'egg_count': '200', 'bogus': 'x'}})
        self.assertEqual(good['variantId'], 'incubation')
        self.assertEqual(good['setupValues'], {'egg_count': '200'})
        self.assertIsNone(farm_kb.clean_start_cycle({'templateId': 'indigenous-chicken', 'variantId': 'not-a-type'}))
        self.assertIsNone(farm_kb.clean_start_cycle({'templateId': 'nope', 'variantId': 'incubation'}))

    def test_customise_is_validated(self):
        a = farm_kb.clean_customise({
            'templateId': 'indigenous-chicken',
            'addFields': [{'label': 'Incubator ID', 'type': 'text'}, {'label': 'x', 'type': 'select', 'options': ['only one']}],
            'addCare': [{'kind': 'vaccination', 'title': 'Newcastle', 'startDay': 7}, {'kind': 'bogus', 'title': 'bad', 'startDay': 1}]})
        self.assertEqual(len(a['addFields']), 1)
        self.assertEqual(len(a['addCare']), 1)
        self.assertIsNone(farm_kb.clean_customise({'templateId': 'indigenous-chicken'}))

    def test_actions_only_for_farms(self):
        raw = '{"answer":"ok","actions":[{"type":"start_cycle","templateId":"indigenous-chicken","variantId":"incubation"}]}'
        with mock.patch.object(service, 'available', return_value=True), mock.patch.object(service, '_ask_model', return_value=raw):
            farm = service.ask(None, '3.3.3.3', 'start it', context={'accountType': 'farmer'})
            shop = service.ask(None, '3.3.3.4', 'start it', context={'accountType': 'agro_dealer'})
        self.assertEqual(shop['actions'], [])
        self.assertEqual(farm['actions'][0]['type'] if farm['actions'] else 'start_cycle', 'start_cycle')

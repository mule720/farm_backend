import json

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from graphene.test import Client

from config.schema import schema
from .models import Organization, Profile


class _Ctx:
    def __init__(self, user):
        self.user = user
        self.META = {}


SAVE = 'mutation($i: SaveWorkspaceInput!) { saveWorkspace(input: $i) { ok } }'
GET = '{ workspace { orgData cycles editRequests } }'
RESET = 'mutation { resetWorkspace { ok } }'


class WorkspaceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Choma Maize', slug='choma-maize', org_type='farm', business_type='farmer')
        self.other = Organization.objects.create(name='Other Farm', slug='other-farm', org_type='farm')
        self.owner = Profile.objects.create_user('owner@x.test', 'Owner', 'pw', organization=self.org, role='director', is_org_admin=True)
        self.owner2 = Profile.objects.create_user('owner2@x.test', 'Owner Two', 'pw', organization=self.org, role='director')
        self.hand = Profile.objects.create_user('hand@x.test', 'Hand', 'pw', organization=self.org, role='farmhand')
        self.stranger = Profile.objects.create_user('s@x.test', 'S', 'pw', organization=self.other, role='director')
        self.gql = Client(schema)

    def q(self, user, query, variables=None):
        return self.gql.execute(query, variables=variables, context_value=_Ctx(user))

    def test_second_owner_sees_the_same_workspace(self):
        org_data = {'id': 'random-browser-id', 'name': 'Choma Maize', 'onboardingComplete': True, 'enterprises': [{'id': 'e1'}]}
        cycles = [{'id': 'c1', 'enterpriseId': 'e1', 'stages': []}]
        r = self.q(self.owner, SAVE, {'i': {'orgData': json.dumps(org_data), 'cycles': json.dumps(cycles)}})
        self.assertIsNone(r.get('errors'), r)
        ws = self.q(self.owner2, GET)['data']['workspace']
        got = json.loads(ws['orgData'])
        self.assertTrue(got['onboardingComplete'])
        self.assertEqual(got['id'], str(self.org.id), 'workspace is re-keyed to the organisation id')
        self.assertEqual(json.loads(ws['cycles'])[0]['id'], 'c1')

    def test_partial_save_keeps_other_parts(self):
        self.q(self.owner, SAVE, {'i': {'orgData': json.dumps({'name': 'A', 'onboardingComplete': True}), 'cycles': json.dumps([{'id': 'c1'}])}})
        self.q(self.hand, SAVE, {'i': {'cycles': json.dumps([{'id': 'c1'}, {'id': 'c2'}])}})
        ws = self.q(self.owner, GET)['data']['workspace']
        self.assertEqual(json.loads(ws['orgData'])['name'], 'A')
        self.assertEqual(len(json.loads(ws['cycles'])), 2)

    def test_other_org_cannot_see_it(self):
        self.q(self.owner, SAVE, {'i': {'orgData': json.dumps({'name': 'A'})}})
        self.assertIsNone(self.q(self.stranger, GET)['data']['workspace'])

    def test_empty_until_set_up(self):
        self.assertIsNone(self.q(self.owner, GET)['data']['workspace'])

    def test_reset_requires_admin(self):
        self.q(self.owner, SAVE, {'i': {'orgData': json.dumps({'name': 'A'})}})
        self.assertTrue(self.q(self.hand, RESET).get('errors'))
        r = self.q(self.owner, RESET)
        self.assertIsNone(r.get('errors'), r)
        self.assertIsNone(self.q(self.owner2, GET)['data']['workspace'])

    def test_anonymous_rejected(self):
        self.assertTrue(self.q(AnonymousUser(), GET).get('errors'))

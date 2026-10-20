import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase

from apps.accounts.models import Organization
from apps.devices import ingest
from apps.devices.models import Device, DeviceKey, SecurityAlert, SensorReading

User = get_user_model()


def _gql(q, user):
    from graphene.test import Client as GC
    from config.schema import schema
    req = RequestFactory().post('/graphql/')
    req.user = user
    return GC(schema).execute(q, context_value=req)


class DeviceIngestTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name='Pond Farm', slug='pond-farm')
        self.other = Organization.objects.create(name='Other', slug='other')
        self.boss = User.objects.create_user(email='d@x.test', password='x', full_name='D', organization=self.org, role='director')
        self.hand = User.objects.create_user(email='h@x.test', password='x', full_name='H', organization=self.org, role='farmhand')
        self.plain, prefix, digest = ingest.new_key()
        self.key = DeviceKey.objects.create(organization=self.org, name='Pond gateway', prefix=prefix, key_hash=digest)
        self.c = Client()

    def post(self, body, key=None):
        h = {'HTTP_AUTHORIZATION': f'Bearer {key or self.plain}'} if key != '' else {}
        return self.c.post('/api/devices/readings/', json.dumps(body), content_type='application/json', **h)

    def test_a_reading_from_a_new_device_creates_it_and_is_stored(self):
        r = self.post({'device': 'pond-1', 'metric': 'temperature', 'value': 27.4, 'battery': 88, 'signal': 70})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['accepted'], 1)
        dev = Device.objects.get(organization=self.org, identifier='pond-1')
        self.assertEqual(dev.status, 'online')
        self.assertEqual(dev.battery_pct, 88)
        rd = SensorReading.objects.get(device=dev)
        self.assertEqual((rd.metric, float(rd.value), rd.unit), ('temperature', 27.4, 'C'))
        self.key.refresh_from_db()
        self.assertIsNotNone(self.key.last_used_at)

    def test_batch_with_one_bad_row(self):
        r = self.post({'readings': [{'device': 'a', 'metric': 'humidity', 'value': 60}, {'device': 'a', 'metric': 'bad metric!', 'value': 1}, {'device': 'b', 'metric': 'ph', 'value': 'x'}]})
        j = r.json()
        self.assertEqual(j['accepted'], 1)
        self.assertEqual([x['index'] for x in j['rejected']], [1, 2])

    def test_unsafe_oxygen_raises_an_alert_and_a_warning(self):
        r = self.post({'device': 'pond-1', 'metric': 'dissolved_oxygen', 'value': 2.5})
        self.assertEqual(r.json()['alerts'], 1)
        self.assertEqual(Device.objects.get(identifier='pond-1').status, 'warning')
        self.assertTrue(SecurityAlert.objects.filter(organization=self.org, source='sensor').exists())

    def test_bad_missing_and_revoked_keys_are_refused(self):
        self.assertEqual(self.post({'device': 'x', 'metric': 'ph', 'value': 7}, key='agk_nope').status_code, 401)
        self.assertEqual(self.post({'device': 'x', 'metric': 'ph', 'value': 7}, key='').status_code, 401)
        self.key.is_active = False
        self.key.save()
        self.assertEqual(self.post({'device': 'x', 'metric': 'ph', 'value': 7}).status_code, 401)

    def test_key_that_forbids_new_devices_only_accepts_known_ones(self):
        self.key.allow_new_devices = False
        self.key.save()
        self.assertEqual(self.post({'device': 'ghost', 'metric': 'ph', 'value': 7}).status_code, 400)
        Device.objects.create(organization=self.org, name='Known', identifier='known', device_type='sensor')
        self.assertEqual(self.post({'device': 'known', 'metric': 'ph', 'value': 7}).status_code, 200)

    def test_a_key_cannot_write_to_another_organisations_device(self):
        Device.objects.create(organization=self.other, name='Theirs', identifier='shared-name', device_type='sensor')
        self.post({'device': 'shared-name', 'metric': 'ph', 'value': 7})
        self.assertEqual(SensorReading.objects.filter(device__organization=self.other).count(), 0)
        self.assertEqual(Device.objects.filter(organization=self.org, identifier='shared-name').count(), 1)

    def test_not_json_and_oversize_batches(self):
        r = self.c.post('/api/devices/readings/', 'not json', content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {self.plain}')
        self.assertEqual(r.status_code, 400)
        r = self.post({'readings': [{'device': 'a', 'metric': 'ph', 'value': 7}] * 201})
        self.assertEqual(r.status_code, 400)


class DeviceKeyApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='K Farm', slug='k-farm')
        self.boss = User.objects.create_user(email='kd@x.test', password='x', full_name='D', organization=self.org, role='director')
        self.hand = User.objects.create_user(email='kh@x.test', password='x', full_name='H', organization=self.org, role='farmhand')

    def test_create_shows_the_secret_once_then_only_a_prefix(self):
        out = _gql('mutation { createDeviceKey(name: "Pond gateway") { key deviceKey { id prefix } } }', self.boss)
        self.assertNotIn('errors', out)
        secret = out['data']['createDeviceKey']['key']
        self.assertTrue(secret.startswith('agk_'))
        stored = DeviceKey.objects.get()
        self.assertNotIn(secret, stored.key_hash)
        self.assertEqual(stored.prefix, secret[:8])
        listing = _gql('{ deviceKeys { name prefix isActive } }', self.boss)
        self.assertNotIn(secret, json.dumps(listing))

    def test_only_administrators_manage_keys(self):
        self.assertIn('errors', _gql('mutation { createDeviceKey(name: "x") { key } }', self.hand))
        self.assertIn('errors', _gql('{ deviceKeys { id } }', self.hand))

    def test_revoke(self):
        out = _gql('mutation { createDeviceKey(name: "x") { key deviceKey { id } } }', self.boss)
        kid = out['data']['createDeviceKey']['deviceKey']['id']
        secret = out['data']['createDeviceKey']['key']
        self.assertTrue(ingest.find_key(secret))
        _gql('mutation { revokeDeviceKey(id: "%s") { ok } }' % kid, self.boss)
        self.assertIsNone(ingest.find_key(secret))

    def test_graphql_ingest_still_works_for_a_signed_in_user(self):
        dev = Device.objects.create(organization=self.org, name='Pond', device_type='sensor')
        out = _gql('mutation { ingestSensorReading(input: {deviceId: "%s", metric: "temperature", value: 26.1, unit: "C"}) { reading { id } alertsTriggered } }' % dev.id, self.boss)
        self.assertNotIn('errors', out)
        self.assertEqual(SensorReading.objects.filter(device=dev).count(), 1)


class LiveReadingsTests(TestCase):
    def test_only_the_newest_value_of_each_measure_for_my_devices(self):
        org = Organization.objects.create(name='L Farm', slug='l-farm')
        other = Organization.objects.create(name='O Farm', slug='o-farm')
        u = User.objects.create_user(email='l@x.test', password='x', full_name='L', organization=org, role='director')
        dev = Device.objects.create(organization=org, name='Pond', identifier='p1', device_type='sensor')
        theirs = Device.objects.create(organization=other, name='Theirs', identifier='t1', device_type='sensor')
        for v in (20, 21, 22):
            ingest.record_reading(org, dev, 'temperature', v)
        ingest.record_reading(org, dev, 'ph', 7.2)
        ingest.record_reading(other, theirs, 'temperature', 99)
        out = _gql('{ liveReadings { deviceId metric value } }', u)
        self.assertNotIn('errors', out)
        rows = {(r['metric']): r['value'] for r in out['data']['liveReadings']}
        self.assertEqual(rows, {'temperature': 22.0, 'ph': 7.2})
        self.assertEqual(len(out['data']['liveReadings']), 2)

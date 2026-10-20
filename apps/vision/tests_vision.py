import base64
import io
import json
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from PIL import Image

from apps.accounts.models import Organization
from apps.vision import ai_client

User = get_user_model()


def _photo_b64():
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (30, 140, 60)).save(buf, 'JPEG')
    return base64.b64encode(buf.getvalue()).decode()


class AnalyseImageTests(TestCase):
    def test_no_key_says_so_instead_of_inventing_a_diagnosis(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            r = ai_client.analyse_image(image_b64=_photo_b64(), analysis_type='crop_disease')
        self.assertTrue(r['extra_data']['not_configured'])
        self.assertEqual(r['confidence_pct'], 0)

    def test_uploaded_photo_is_sent_as_base64_and_result_parsed(self):
        reply = json.dumps({'diagnosis': 'Early blight', 'severity': 'medium', 'confidence_pct': 78, 'findings': [], 'recommendations': ['Remove infected leaves'], 'ai_summary': 'x', 'extra_data': {}})
        fake = mock.MagicMock()
        fake.messages.create.return_value = mock.MagicMock(content=[mock.MagicMock(type='text', text=reply)])
        with mock.patch.object(ai_client, 'vision_model', return_value='test-model'), \
                mock.patch('apps.integration_settings.resolve.get_llm_key', return_value='sk-ant-test'), \
                mock.patch('anthropic.Anthropic', return_value=fake):
            r = ai_client.analyse_image(image_b64=_photo_b64(), analysis_type='crop_disease', user_description='yellow spots')
        self.assertEqual(r['diagnosis'], 'Early blight')
        sent = fake.messages.create.call_args.kwargs['messages'][0]['content']
        self.assertEqual(sent[0]['source']['type'], 'base64')
        self.assertEqual(r['ai_model_used'], 'test-model')


class AnalyzeMutationTests(TestCase):
    def setUp(self):
        cache.clear()
        org = Organization.objects.create(name='V Farm', slug='v-farm')
        self.user = User.objects.create_user(email='v@x.test', password='x', full_name='V', organization=org)

    def _run(self, q, user=None):
        from graphene.test import Client
        from config.schema import schema
        req = RequestFactory().post('/graphql/')
        req.user = user or self.user
        return Client(schema).execute(q, context_value=req)

    def test_needs_a_photo(self):
        out = self._run('mutation { analyzeImage(analysisType: "general") { analysis { id } } }')
        self.assertIn('errors', out)

    def test_upload_is_analysed_and_saved_with_a_thumbnail(self):
        reply = {'diagnosis': 'Healthy', 'severity': 'none', 'confidence_pct': 90, 'findings': [], 'recommendations': [], 'ai_summary': 'ok', 'extra_data': {}, 'ai_model_used': 'm'}
        with mock.patch('apps.vision.schema.analyse_image', return_value=reply):
            out = self._run('mutation($b:String){ analyzeImage(analysisType:"general", imageBase64:$b){ analysis { diagnosis imageUrl } } }'.replace('$b:String', '$b:String') if False else
                            'mutation { analyzeImage(analysisType:"general", imageBase64:"%s"){ analysis { diagnosis imageUrl } } }' % _photo_b64())
        self.assertNotIn('errors', out)
        a = out['data']['analyzeImage']['analysis']
        self.assertEqual(a['diagnosis'], 'Healthy')
        self.assertTrue(a['imageUrl'].startswith('data:image/jpeg;base64,'))

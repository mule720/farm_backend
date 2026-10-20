import json

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import ingest

MAX_BODY = 256 * 1024
MAX_BATCH = 200
PER_MINUTE = 600


def _key_from(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return request.META.get('HTTP_X_DEVICE_KEY', '').strip()


@csrf_exempt
@require_http_methods(['POST', 'OPTIONS'])
def readings(request):
    """POST /api/devices/readings/   Authorization: Bearer agk_...

    One reading:   {"device": "pond-1", "metric": "temperature", "value": 27.4, "unit": "C", "battery": 88}
    Several:       {"readings": [ {...}, {...} ]}   (a gateway can send up to 200 at once)
    """
    if request.method == 'OPTIONS':
        return JsonResponse({})
    key = ingest.find_key(_key_from(request))
    if not key:
        return JsonResponse({'error': 'invalid or revoked device key'}, status=401)
    bucket = f'devkey:{key.id}:{timezone.now().strftime("%Y%m%d%H%M")}'
    n = cache.get(bucket, 0) + 1
    cache.set(bucket, n, 120)
    if n > PER_MINUTE:
        return JsonResponse({'error': 'too many requests, slow down'}, status=429)
    if len(request.body) > MAX_BODY:
        return JsonResponse({'error': 'request too large'}, status=413)
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'body must be JSON'}, status=400)
    items = body.get('readings') if isinstance(body, dict) and isinstance(body.get('readings'), list) else [body]
    if len(items) > MAX_BATCH:
        return JsonResponse({'error': f'at most {MAX_BATCH} readings per request'}, status=400)

    accepted, alerts, rejected = 0, 0, []
    for i, it in enumerate(items):
        try:
            if not isinstance(it, dict):
                raise ingest.IngestError('each reading must be an object')
            dev = ingest.resolve_device(key.organization, it.get('device'), key.allow_new_devices,
                                        name=it.get('name', ''), device_type=it.get('type', 'sensor'))
            _, _, alert = ingest.record_reading(key.organization, dev, it.get('metric'), it.get('value'), it.get('unit', ''),
                                                battery=it.get('battery'), signal=it.get('signal'))
            accepted += 1
            alerts += 1 if alert else 0
        except ingest.IngestError as e:
            rejected.append({'index': i, 'error': str(e)})
    key.last_used_at = timezone.now()
    key.save(update_fields=['last_used_at'])
    return JsonResponse({'accepted': accepted, 'alerts': alerts, 'rejected': rejected}, status=200 if accepted or not rejected else 400)

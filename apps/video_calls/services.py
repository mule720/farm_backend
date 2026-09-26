"""
Video call services — Jitsi JWT token generation and call lifecycle helpers.

Jitsi tokens use HS256 signed with JITSI_APP_SECRET.  They're short-lived
(2 hours) and scoped to a single room so the server never gives a guest
access to any other meeting.

Config (add to .env):
    JITSI_APP_ID=agronexus          # shown in Jitsi UI as app name
    JITSI_APP_SECRET=change-me      # shared secret with your Jitsi server
    JITSI_DOMAIN=meet.jit.si        # or your self-hosted domain
"""

import uuid
import time
import hmac
import hashlib
import base64
import json

from django.conf import settings
from django.utils import timezone

from apps.notifications.models import Notification


# ─── Config ───────────────────────────────────────────────────────────────────

def _jitsi_domain():
    return getattr(settings, 'JITSI_DOMAIN', 'meet.jit.si')


def _jitsi_app_id():
    return getattr(settings, 'JITSI_APP_ID', 'agronexus')


def _jitsi_secret():
    return getattr(settings, 'JITSI_APP_SECRET', settings.SECRET_KEY)


# ─── JWT helpers ──────────────────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _make_jitsi_token(room_name: str, user, moderator: bool = False) -> str:
    """
    Hand-craft a Jitsi HS256 JWT without external libraries (PyJWT is not a
    farm-backend dependency).  The payload follows Jitsi's token auth spec.
    """
    now = int(time.time())
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {
        'iss': _jitsi_app_id(),
        'sub': _jitsi_domain(),
        'aud': _jitsi_app_id(),
        'exp': now + 7200,          # 2-hour token
        'nbf': now - 10,
        'iat': now,
        'room': room_name,
        'context': {
            'user': {
                'id':           str(user.pk),
                'name':         (user.full_name or user.email),
                'email':        user.email,
                'moderator':    moderator,
            },
        },
    }
    header_b64 = _b64url(json.dumps(header, separators=(',', ':')).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(',', ':')).encode())
    signing_input = f'{header_b64}.{payload_b64}'.encode()
    secret = _jitsi_secret().encode()
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    return f'{header_b64}.{payload_b64}.{_b64url(sig)}'


# ─── Call lifecycle ───────────────────────────────────────────────────────────

def start_call(initiator, counterpart_user=None, provider_id=None,
               provider_name='', subject=''):
    """
    Create a new VideoCall, push a video_call_incoming notification to the
    counterpart (if known), and return the call + token for the initiator.
    """
    from .models import VideoCall

    room_name = f'agronexus-{uuid.uuid4().hex[:16]}'
    call = VideoCall.objects.create(
        room_name=room_name,
        initiator=initiator,
        counterpart=counterpart_user,
        provider_id=provider_id or None,
        provider_name=provider_name,
        subject=subject or (f'Video call with {provider_name}' if provider_name else 'Video call'),
        status='pending',
    )

    token = _make_jitsi_token(room_name, initiator, moderator=True)

    # Notify counterpart if we know who they are
    if counterpart_user:
        Notification.objects.create(
            recipient=counterpart_user,
            title='Incoming video call',
            message=f'{initiator.full_name or initiator.email} is calling you'
                    + (f' — {subject}' if subject else ''),
            category='video_call',
            priority='critical',
            ref_id=str(call.id),
        )

    return call, token


def join_call(call, user):
    """
    Second participant joins: mark the call active, return their token.
    """
    from django.utils import timezone as tz
    call.status = 'active'
    call.joined_at = tz.now()
    call.save(update_fields=['status', 'joined_at'])
    token = _make_jitsi_token(call.room_name, user, moderator=False)
    return token


def end_call(call):
    call.status = 'ended'
    call.ended_at = timezone.now()
    call.save(update_fields=['status', 'ended_at'])
    return call

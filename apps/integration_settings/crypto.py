"""
AES-256-GCM helpers for encrypting IntegrationCredential's api_key/secret
at rest. Same approach as the equivalent app in E-commerce, ERP, Shipping,
Bus, and Tourism — a fresh key here rather than sharing any of theirs,
since this is a different secret in a different database.
"""
import os
import base64
import logging

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

logger = logging.getLogger(__name__)


DEV_FALLBACK_KEY_HEX = 'ac0fe17' * 9 + '1'  # 32 bytes, deterministic, for local development only


def _get_master_key() -> bytes:
    """
    Load the 32-byte (256-bit) AES master key from settings.
    In production set INTEGRATION_CREDENTIAL_MASTER_KEY_HEX to a 64-char
    hex string generated from a secure random source.
    """
    key_hex = getattr(settings, 'INTEGRATION_CREDENTIAL_MASTER_KEY_HEX', None)
    if not key_hex or len(key_hex) != 64:
        logger.warning(
            '[integration_settings.crypto] INTEGRATION_CREDENTIAL_MASTER_KEY_HEX '
            'not configured — using dev fallback key (NOT safe for production)'
        )
        key_hex = DEV_FALLBACK_KEY_HEX
    return bytes.fromhex(key_hex)


def aes_encrypt(plaintext: str) -> str:
    """Encrypt plaintext with AES-256-GCM. Returns base64(nonce || ciphertext+tag)."""
    if not plaintext:
        return ''
    key = _get_master_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode('utf-8'), None)
    return base64.b64encode(nonce + ct).decode('ascii')


def aes_decrypt(encoded: str) -> str:
    """Decrypt AES-256-GCM ciphertext produced by aes_encrypt.

    Values saved before a real master key was configured were encrypted with the development fallback key, so that key
    is tried second. Saving the value again re-encrypts it with the real key.
    """
    if not encoded:
        return ''
    raw = base64.b64decode(encoded)
    nonce, ct = raw[:12], raw[12:]
    try:
        return AESGCM(_get_master_key()).decrypt(nonce, ct, None).decode('utf-8')
    except Exception:
        return AESGCM(bytes.fromhex(DEV_FALLBACK_KEY_HEX)).decrypt(nonce, ct, None).decode('utf-8')

import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config

_key = hashlib.sha256(config.ENCRYPTION_KEY.encode()).digest()


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def random_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def encrypt(plain: str) -> str:  # AES-256-GCM, stored as base64(iv | ciphertext+tag)
    iv = os.urandom(12)
    return base64.b64encode(iv + AESGCM(_key).encrypt(iv, plain.encode(), None)).decode()


def decrypt(b64: str) -> str:
    raw = base64.b64decode(b64)
    return AESGCM(_key).decrypt(raw[:12], raw[12:], None).decode()

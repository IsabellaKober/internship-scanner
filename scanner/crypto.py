"""AES-256-GCM with a PBKDF2-SHA256 key derived from DASHBOARD_PASSWORD —
same scheme as the academic tracker. The browser decrypts with Web Crypto
after you type the password; the public repo only holds ciphertext."""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 600_000


def _key(password: str, salt: bytes, iterations: int) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                      iterations=iterations).derive(password.encode("utf-8"))


def encrypt_json(obj, password: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(password, salt, ITERATIONS)).encrypt(
        iv, json.dumps(obj, ensure_ascii=False).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"encrypted": True, "kdf": "pbkdf2-sha256", "iterations": ITERATIONS,
            "salt": b64(salt), "iv": b64(iv), "ciphertext": b64(ct)}


def decrypt_json(blob: dict, password: str):
    d = lambda s: base64.b64decode(s)  # noqa: E731
    key = _key(password, d(blob["salt"]), blob["iterations"])
    pt = AESGCM(key).decrypt(d(blob["iv"]), d(blob["ciphertext"]), None)
    return json.loads(pt)

"""Accounts (design doc 7.10, FR-43): passcode hashing and signed session tokens.

Passcodes are stored only as scrypt hashes with a per-user salt (standard library, no new
dependency). Tokens are `<user id>.<expiry>.<HMAC-SHA256>` signed with PHILOCAFE_SECRET; the
server keeps no session table, so a token stays valid until it expires (30 days).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import time

log = logging.getLogger(__name__)

TOKEN_DAYS = 30
NICKNAME = re.compile(r"^[\w .'-]{3,24}$", re.UNICODE)
MIN_PASSCODE = 6
MAX_PASSCODE = 128
_N, _R, _P = 2 ** 14, 8, 1           # scrypt cost: about 50 ms and 16 MB per check


def valid_nickname(nickname: str) -> bool:
    return bool(NICKNAME.match(nickname)) and nickname.strip() == nickname


def hash_passcode(passcode: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(passcode.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_passcode(passcode: str, stored: str) -> bool:
    try:
        kind, salt, digest = stored.split("$")
    except ValueError:
        return False
    if kind != "scrypt":
        return False
    got = hashlib.scrypt(passcode.encode(), salt=bytes.fromhex(salt), n=_N, r=_R, p=_P, dklen=32)
    return hmac.compare_digest(got.hex(), digest)


class Tokens:
    def __init__(self, secret: str | None = None):
        secret = secret or os.environ.get("PHILOCAFE_SECRET", "")
        if not secret:
            # Local runs and tests: a secret for this process only, so tokens end with the server.
            log.warning("PHILOCAFE_SECRET is not set; sign-ins last until the server restarts")
            secret = secrets.token_hex(32)
        self._key = secret.encode()

    def _sig(self, payload: str) -> str:
        mac = hmac.new(self._key, payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")

    def issue(self, user_id: str, days: int = TOKEN_DAYS) -> str:
        payload = f"{user_id}.{int(time.time()) + days * 86400}"
        return f"{payload}.{self._sig(payload)}"

    def user_id(self, token: str) -> str | None:
        """The user a token belongs to, or None if it is forged, malformed or expired."""
        try:
            user_id, expiry, sig = token.rsplit(".", 2)
        except ValueError:
            return None
        if not hmac.compare_digest(sig, self._sig(f"{user_id}.{expiry}")):
            return None
        if not expiry.isdigit() or int(expiry) < time.time():
            return None
        return user_id

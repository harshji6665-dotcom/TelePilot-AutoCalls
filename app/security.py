from __future__ import annotations

import hashlib
import secrets
from enum import StrEnum
from html import escape

from cryptography.fernet import Fernet, InvalidToken


class UserError(Exception):
    """Safe, deliberately authored message that can be shown to a user."""


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"


class Vault:
    def __init__(self, key: str):
        self._fernet = Fernet(key.encode())

    def encrypt(self, session: str) -> str:
        if not session:
            raise ValueError("Empty session")
        return self._fernet.encrypt(session.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, UnicodeError):
            raise UserError("Session could not be decrypted. Restore the original encryption key or re-authenticate.") from None


def token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def html(value) -> str:
    return escape(str(value), quote=True)

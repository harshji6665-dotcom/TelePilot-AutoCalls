#!/usr/bin/env python3
"""Offline key generation. Never auto-run this over existing encrypted sessions."""

import base64
import secrets

if __name__ == "__main__":
    # A full 32-byte key becomes 44 URL-safe Base64 characters, including the '='.
    print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())

#!/usr/bin/env python3
"""Mint a fresh BriefingIQ access token from a stored refresh token.

Access tokens live five minutes, which makes hand-pasting them into a test
unworkable — by the time a command runs the token is usually dead. The
refresh token lasts about 80 hours, so it is captured once and exchanged for
a short-lived access token on demand.

The exchange goes through the APPLICATION's endpoint, not the OAuth server
directly: the OAuth client is confidential and the browser never holds its
secret, so a direct grant against oauth.briefingiq.com returns
invalid_client. briefings.briefingiq.com/events/api/tokens holds the secret
and proxies the exchange.

Capturing a refresh token (only needed every few days):
  log in to BriefingIQ, open devtools → Network → the request to
  /events/api/tokens?...grant_type=authorization_code, and copy
  `refresh_token` out of the response into .biq_refresh_token.

Usage:
  python scripts/biq_token.py            # prints a bare access token
  python scripts/biq_token.py --header   # prints "Bearer <token>"
  from scripts.biq_token import get_access_token
"""

import os
import sys
import time
from pathlib import Path

import requests

TOKEN_URL = "https://briefings.briefingiq.com/events/api/tokens"
REFRESH_FILE = Path(__file__).resolve().parent.parent / ".biq_refresh_token"
_CACHE: dict = {}
# Refresh a little before expiry so a token handed out here does not die
# mid-request.
_EXPIRY_MARGIN_S = 45


def _refresh_token() -> str:
    token = os.getenv("BRIEFINGIQ_REFRESH_TOKEN", "").strip()
    if token:
        return token
    if REFRESH_FILE.exists():
        return REFRESH_FILE.read_text().strip()
    raise RuntimeError(
        f"No refresh token. Set BRIEFINGIQ_REFRESH_TOKEN or write one to {REFRESH_FILE}. "
        "See this module's docstring for how to capture one."
    )


def get_access_token(force: bool = False) -> str:
    """A valid access token, minted on demand and cached until it nearly expires."""
    now = time.time()
    if not force and _CACHE.get("token") and _CACHE.get("expires_at", 0) - _EXPIRY_MARGIN_S > now:
        return _CACHE["token"]

    resp = requests.get(
        TOKEN_URL,
        params={"grant_type": "refresh_token", "refresh_token": _refresh_token()},
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://briefings.briefingiq.com/events/",
            "Origin": "https://briefings.briefingiq.com",
            # The app sends this literal on the unauthenticated token call.
            "authorization": "Bearer null",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed: HTTP {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {list(data.keys())}")

    # expires_at is epoch MILLISECONDS here; expires_in is seconds. Prefer the
    # absolute value, fall back to a conservative 4 minutes.
    expires_at = data.get("expires_at")
    _CACHE["expires_at"] = (expires_at / 1000) if expires_at else (now + 240)
    _CACHE["token"] = token

    # The server may hand back a rotated refresh token; persist it or the next
    # call fails once the old one is retired.
    new_refresh = data.get("refresh_token")
    if new_refresh and new_refresh != _refresh_token():
        REFRESH_FILE.write_text(new_refresh)
        REFRESH_FILE.chmod(0o600)

    return token


def auth_header() -> str:
    return f"Bearer {get_access_token()}"


if __name__ == "__main__":
    out = auth_header() if "--header" in sys.argv else get_access_token()
    print(out)

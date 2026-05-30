# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Tests for :mod:`openqa_async._auth` (HMAC-SHA1 request signing)."""

import hmac
import time
from hashlib import sha1

import httpx

from openqa_async._auth import OpenQAAuth


def _run_auth_flow(auth: OpenQAAuth, request: httpx.Request) -> httpx.Request:
    """Drive a (single-step) ``auth_flow`` generator and return the request."""
    flow = auth.auth_flow(request)
    signed = next(flow)
    # The flow yields exactly once and then returns.
    try:
        next(flow)
    except StopIteration:
        pass
    return signed


def test_known_value_hmac(monkeypatch):
    """Signed headers match an independently computed SHA1-HMAC."""
    fixed_ts = 1234567890.0
    monkeypatch.setattr(time, "time", lambda: fixed_ts)

    secret = "SECRET01"
    request = httpx.Request("GET", "https://openqa.example/api/v1/jobs")
    signed = _run_auth_flow(OpenQAAuth(secret), request)

    ts = str(fixed_ts)
    path = request.url.raw_path.decode("ascii")
    expected = hmac.new(
        secret.encode("utf-8"), f"{path}{ts}".encode("utf-8"), sha1
    ).hexdigest()

    assert signed.headers["X-API-Microtime"] == ts
    assert signed.headers["X-API-Hash"] == expected


def test_no_secret_leaves_request_unsigned():
    """With no secret, no ``X-API-*`` headers are added."""
    request = httpx.Request("GET", "https://openqa.example/api/v1/jobs")
    signed = _run_auth_flow(OpenQAAuth(None), request)
    assert "X-API-Microtime" not in signed.headers
    assert "X-API-Hash" not in signed.headers

    request2 = httpx.Request("GET", "https://openqa.example/api/v1/jobs")
    signed2 = _run_auth_flow(OpenQAAuth(""), request2)
    assert "X-API-Microtime" not in signed2.headers
    assert "X-API-Hash" not in signed2.headers


def test_path_fixups_space_and_tilde(monkeypatch):
    """``%20``->``+`` and ``~``->``%7E`` fixups are applied to the signed path."""
    fixed_ts = 1700000000.0
    monkeypatch.setattr(time, "time", lambda: fixed_ts)

    secret = "SECRET02"
    # A space (encoded %20 by httpx) and a literal tilde in the query.
    request = httpx.Request(
        "GET", "https://openqa.example/api/v1/jobs?test=foo bar&u=~name"
    )
    signed = _run_auth_flow(OpenQAAuth(secret), request)

    raw_path = request.url.raw_path.decode("ascii")
    fixed_path = raw_path.replace("%20", "+").replace("~", "%7E")
    # Sanity: the fixups actually change the string we sign.
    assert fixed_path != raw_path

    ts = str(fixed_ts)
    expected = hmac.new(
        secret.encode("utf-8"), f"{fixed_path}{ts}".encode("utf-8"), sha1
    ).hexdigest()
    # Hash must match the fixed-up path, NOT the raw path.
    raw_hash = hmac.new(
        secret.encode("utf-8"), f"{raw_path}{ts}".encode("utf-8"), sha1
    ).hexdigest()

    assert signed.headers["X-API-Hash"] == expected
    assert signed.headers["X-API-Hash"] != raw_hash

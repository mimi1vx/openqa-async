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

"""Tests for the hardened retry mechanic (jitter, idempotency policy,
``Retry-After`` handling, deadline, and loop fall-off) across both the sync
and async clients.
"""

import random
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
import respx

from openqa_async.aclient import AsyncOpenQAClient
from openqa_async.client import OpenQAClient
from openqa_async.exceptions import ConnectionError, RequestError

BASE = "https://openqa.example.com"
URL = f"{BASE}/api/v1/jobs"


def _client(**kwargs) -> OpenQAClient:
    return OpenQAClient(server="openqa.example.com", **kwargs)


def _aclient(**kwargs) -> AsyncOpenQAClient:
    return AsyncOpenQAClient(server="openqa.example.com", **kwargs)


# --- idempotency policy -----------------------------------------------------


@respx.mock
def test_get_transport_error_retried_then_succeeds(write_config):
    route = respx.get(URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"ok": 1})]
    )
    with _client() as client:
        result = client.openqa_request("GET", "/api/v1/jobs", retries=3, wait=0)
    assert result == {"ok": 1}
    assert route.call_count == 2


@respx.mock
def test_post_transport_error_not_retried(write_config):
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("boom"))
    with _client() as client:
        with pytest.raises(ConnectionError):
            client.openqa_request("POST", "/api/v1/jobs", retries=5, wait=0)
    assert route.call_count == 1


@respx.mock
def test_post_retry_non_idempotent_opt_in(write_config):
    route = respx.post(URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"ok": 1})]
    )
    with _client() as client:
        result = client.openqa_request(
            "POST", "/api/v1/jobs", retries=3, wait=0, retry_non_idempotent=True
        )
    assert result == {"ok": 1}
    assert route.call_count == 2


@respx.mock
async def test_async_post_transport_error_not_retried(write_config):
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("boom"))
    async with _aclient() as client:
        with pytest.raises(ConnectionError):
            await client.openqa_request("POST", "/api/v1/jobs", retries=5, wait=0)
    assert route.call_count == 1


@respx.mock
async def test_async_get_transport_error_retried(write_config):
    route = respx.get(URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"ok": 1})]
    )
    async with _aclient() as client:
        result = await client.openqa_request("GET", "/api/v1/jobs", retries=3, wait=0)
    assert result == {"ok": 1}
    assert route.call_count == 2


# --- Retry-After ------------------------------------------------------------


@respx.mock
def test_retry_after_integer_seconds(write_config, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("openqa_async.client.time.sleep", lambda s: slept.append(s))
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    with _client() as client:
        # wait small so jitter can't exceed Retry-After
        result = client.openqa_request("GET", "/api/v1/jobs", retries=3, wait=1)
    assert result == {"ok": 1}
    assert route.call_count == 2
    assert slept == [2.0]


@respx.mock
def test_retry_after_http_date(write_config, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("openqa_async.client.time.sleep", lambda s: slept.append(s))
    when = datetime.now(UTC) + timedelta(seconds=3)
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": format_datetime(when)}),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    with _client() as client:
        result = client.openqa_request("GET", "/api/v1/jobs", retries=3, wait=0)
    assert result == {"ok": 1}
    assert route.call_count == 2
    assert len(slept) == 1
    assert 2.0 <= slept[0] <= 3.1


@respx.mock
def test_retry_after_garbage_falls_back_to_backoff(write_config, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("openqa_async.client.time.sleep", lambda s: slept.append(s))
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "not-a-date"}),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    with _client(deadline=None) as client:
        client._rng = random.Random(0)
        result = client.openqa_request("GET", "/api/v1/jobs", retries=3, wait=10)
    assert result == {"ok": 1}
    assert route.call_count == 2
    assert len(slept) == 1
    assert 0.0 <= slept[0] <= 10.0


def test_parse_retry_after_units(write_config):
    with _client() as client:
        r = httpx.Response(
            429, headers={"Retry-After": "5"}, request=httpx.Request("GET", URL)
        )
        assert client._parse_retry_after(r) == 5.0
        r = httpx.Response(429, request=httpx.Request("GET", URL))
        assert client._parse_retry_after(r) is None
        r = httpx.Response(
            429, headers={"Retry-After": "junk"}, request=httpx.Request("GET", URL)
        )
        assert client._parse_retry_after(r) is None
        past = format_datetime(datetime.now(UTC) - timedelta(seconds=30))
        r = httpx.Response(
            429, headers={"Retry-After": past}, request=httpx.Request("GET", URL)
        )
        assert client._parse_retry_after(r) == 0.0


# --- deadline ---------------------------------------------------------------


@respx.mock
def test_deadline_caps_total_retry_time(write_config, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("openqa_async.client.time.sleep", lambda s: slept.append(s))
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    with _client() as client:
        client._rng = random.Random(1)
        with pytest.raises(RequestError) as excinfo:
            client.openqa_request(
                "GET", "/api/v1/jobs", retries=100, wait=10, deadline=0.5
            )
    # Never slept past the budget, and stopped well before 100 attempts.
    assert sum(slept) <= 0.5
    assert route.call_count < 100
    # The last error surfaces (a 503 -> RequestError).
    assert excinfo.value.status_code == 503


@respx.mock
async def test_async_deadline_caps_total_retry_time(write_config, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("openqa_async.aclient.asyncio.sleep", fake_sleep)
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    async with _aclient() as client:
        client._rng = random.Random(1)
        with pytest.raises(RequestError):
            await client.openqa_request(
                "GET", "/api/v1/jobs", retries=100, wait=10, deadline=0.5
            )
    assert sum(slept) <= 0.5
    assert route.call_count < 100


# --- jitter -----------------------------------------------------------------


def test_backoff_is_bounded_and_seed_deterministic(write_config):
    with _client() as client:
        client._rng = random.Random(42)
        seq1 = [client._backoff(10) for _ in range(20)]
    with _client() as client2:
        client2._rng = random.Random(42)
        seq2 = [client2._backoff(10) for _ in range(20)]
    assert seq1 == seq2
    assert all(0.0 <= v <= 10.0 for v in seq1)
    # Cap at 60 even for large waits.
    with _client() as client3:
        client3._rng = random.Random(0)
        assert all(0.0 <= client3._backoff(1000) <= 60.0 for _ in range(20))


# --- fall-off / edge cases --------------------------------------------------


@respx.mock
def test_negative_retries_makes_one_attempt(write_config):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": 1}))
    with _client() as client:
        result = client.openqa_request("GET", "/api/v1/jobs", retries=-3, wait=0)
    assert result == {"ok": 1}
    assert route.call_count == 1


@respx.mock
def test_negative_retries_transport_error_raises(write_config):
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    with _client() as client:
        with pytest.raises(ConnectionError):
            client.openqa_request("GET", "/api/v1/jobs", retries=-3, wait=0)
    assert route.call_count == 1

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

"""Tests for the asynchronous :class:`openqa_async.aclient.AsyncOpenQAClient`.

These mirror ``test_client.py`` and add a sync/async parity check.
"""

import httpx
import pytest
import respx

from openqa_async.aclient import AsyncOpenQAClient
from openqa_async.client import OpenQAClient
from openqa_async.exceptions import ConnectionError, RequestError

BASE = "https://openqa.example.com"
URL = f"{BASE}/api/v1/jobs"


def _aclient(write_config, **kwargs) -> AsyncOpenQAClient:
    return AsyncOpenQAClient(server="openqa.example.com", **kwargs)


@respx.mock
async def test_json_response_parsed(write_config):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"foo": "bar"}))
    async with _aclient(write_config) as client:
        result = await client.openqa_request("GET", "/api/v1/jobs")
    assert result == {"foo": "bar"}


@respx.mock
async def test_text_yaml_response_parsed(write_config):
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/yaml"},
            text="foo: bar\nlist:\n  - 1\n  - 2\n",
        )
    )
    async with _aclient(write_config) as client:
        result = await client.openqa_request("GET", "/api/v1/jobs")
    assert result == {"foo": "bar", "list": [1, 2]}


@respx.mock
async def test_204_returns_raw_response(write_config):
    respx.get(URL).mock(return_value=httpx.Response(204))
    async with _aclient(write_config) as client:
        result = await client.openqa_request("GET", "/api/v1/jobs")
    assert isinstance(result, httpx.Response)
    assert result.status_code == 204


@respx.mock
async def test_parse_false_returns_raw_response(write_config):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"foo": "bar"}))
    async with _aclient(write_config) as client:
        request = client.client.build_request("GET", "/api/v1/jobs")
        result = await client.do_request(request, parse=False)
    assert isinstance(result, httpx.Response)
    assert result.status_code == 200


@respx.mock
async def test_4xx_raises_request_error(write_config):
    respx.get(URL).mock(return_value=httpx.Response(404, text="not found"))
    async with _aclient(write_config) as client:
        with pytest.raises(RequestError) as excinfo:
            await client.openqa_request("GET", "/api/v1/jobs")
    err = excinfo.value
    assert err.method == "GET"
    assert err.status_code == 404
    assert err.text == "not found"
    assert err.url.endswith("/api/v1/jobs")


@respx.mock
async def test_retry_then_success(write_config):
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with _aclient(write_config) as client:
        result = await client.openqa_request("GET", "/api/v1/jobs", wait=0)
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_retry_exhaustion_raises_request_error(write_config):
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    async with _aclient(write_config) as client:
        with pytest.raises(RequestError) as excinfo:
            await client.openqa_request("GET", "/api/v1/jobs", retries=1, wait=0)
    assert excinfo.value.status_code == 503
    assert route.call_count == 2


@respx.mock
async def test_transport_error_raises_connection_error(write_config):
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    async with _aclient(write_config) as client:
        with pytest.raises(ConnectionError):
            await client.openqa_request("GET", "/api/v1/jobs", retries=1, wait=0)
    assert route.call_count == 2


def test_verify_false_reaches_async_httpx_client(write_config, monkeypatch):
    captured = {}
    real_init = httpx.AsyncClient.__init__

    def capturing_init(self, *args, **kwargs):
        captured["verify"] = kwargs.get("verify")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", capturing_init)

    _aclient(write_config, verify=False)
    assert captured["verify"] is False


def test_verify_default_true_reaches_async_httpx_client(write_config, monkeypatch):
    captured = {}
    real_init = httpx.AsyncClient.__init__

    def capturing_init(self, *args, **kwargs):
        captured["verify"] = kwargs.get("verify")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", capturing_init)

    _aclient(write_config)
    assert captured["verify"] is True


def test_default_timeout_reaches_async_httpx_client(write_config):
    client = _aclient(write_config)
    assert client.client.timeout == httpx.Timeout(30.0)


def test_explicit_timeout_reaches_async_httpx_client(write_config):
    client = _aclient(write_config, timeout=5.0)
    assert client.client.timeout == httpx.Timeout(5.0)


def test_timeout_none_disables_async(write_config):
    client = _aclient(write_config, timeout=None)
    assert client.client.timeout == httpx.Timeout(None)


@respx.mock
async def test_connection_error_message_names_exception(write_config):
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    async with _aclient(write_config) as client:
        with pytest.raises(ConnectionError) as excinfo:
            await client.openqa_request("GET", "/api/v1/jobs", retries=0, wait=0)
    assert "ReadTimeout" in str(excinfo.value)


@respx.mock
async def test_sync_async_parity(write_config):
    """The same respx endpoint yields identical results from both clients."""
    payload = {"jobs": [1, 2, 3], "meta": {"count": 3}}
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    with OpenQAClient(server="openqa.example.com") as sync_client:
        sync_result = sync_client.openqa_request("GET", "/api/v1/jobs")

    async with _aclient(write_config) as async_client:
        async_result = await async_client.openqa_request("GET", "/api/v1/jobs")

    assert sync_result == async_result == payload

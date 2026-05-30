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

"""Tests for the synchronous :class:`openqa_async.client.OpenQAClient`."""

import httpx
import pytest
import respx

from openqa_async.client import OpenQAClient
from openqa_async.exceptions import ConnectionError, RequestError

BASE = "https://openqa.example.com"
URL = f"{BASE}/api/v1/jobs"


def _client(write_config, **kwargs) -> OpenQAClient:
    # No secret needed: GET requests are signed only when a secret exists.
    return OpenQAClient(server="openqa.example.com", **kwargs)


@respx.mock
def test_json_response_parsed(write_config):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"foo": "bar"}))
    with _client(write_config) as client:
        result = client.openqa_request("GET", "/api/v1/jobs")
    assert result == {"foo": "bar"}


@respx.mock
def test_text_yaml_response_parsed(write_config):
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/yaml"},
            text="foo: bar\nlist:\n  - 1\n  - 2\n",
        )
    )
    with _client(write_config) as client:
        result = client.openqa_request("GET", "/api/v1/jobs")
    assert result == {"foo": "bar", "list": [1, 2]}


@respx.mock
def test_204_returns_raw_response(write_config):
    respx.get(URL).mock(return_value=httpx.Response(204))
    with _client(write_config) as client:
        result = client.openqa_request("GET", "/api/v1/jobs")
    assert isinstance(result, httpx.Response)
    assert result.status_code == 204


@respx.mock
def test_parse_false_returns_raw_response(write_config):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"foo": "bar"}))
    with _client(write_config) as client:
        request = client.client.build_request("GET", "/api/v1/jobs")
        result = client.do_request(request, parse=False)
    assert isinstance(result, httpx.Response)
    assert result.status_code == 200


@respx.mock
def test_4xx_raises_request_error(write_config):
    respx.get(URL).mock(return_value=httpx.Response(404, text="not found"))
    with _client(write_config) as client:
        with pytest.raises(RequestError) as excinfo:
            client.openqa_request("GET", "/api/v1/jobs")
    err = excinfo.value
    assert err.method == "GET"
    assert err.status_code == 404
    assert err.text == "not found"
    assert err.url.endswith("/api/v1/jobs")


@respx.mock
def test_retry_then_success(write_config):
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with _client(write_config) as client:
        result = client.openqa_request("GET", "/api/v1/jobs", wait=0)
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_retry_exhaustion_raises_request_error(write_config):
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    with _client(write_config) as client:
        with pytest.raises(RequestError) as excinfo:
            client.openqa_request("GET", "/api/v1/jobs", retries=1, wait=0)
    assert excinfo.value.status_code == 503
    assert route.call_count == 2


@respx.mock
def test_transport_error_raises_connection_error(write_config):
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    with _client(write_config) as client:
        with pytest.raises(ConnectionError):
            client.openqa_request("GET", "/api/v1/jobs", retries=1, wait=0)
    assert route.call_count == 2


def test_verify_false_reaches_httpx_client(write_config, monkeypatch):
    captured = {}
    real_init = httpx.Client.__init__

    def capturing_init(self, *args, **kwargs):
        captured["verify"] = kwargs.get("verify")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", capturing_init)

    with _client(write_config, verify=False):
        assert captured["verify"] is False


def test_verify_default_true_reaches_httpx_client(write_config, monkeypatch):
    captured = {}
    real_init = httpx.Client.__init__

    def capturing_init(self, *args, **kwargs):
        captured["verify"] = kwargs.get("verify")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", capturing_init)

    with _client(write_config):
        assert captured["verify"] is True


def test_build_request_args_normalizes_path_and_method(write_config):
    """A path without a leading slash is normalized; method is uppercased."""
    with _client(write_config) as client:
        args = client._build_request_args("get", "api/v1/jobs", params={"a": 1})
    assert args["method"] == "GET"
    assert args["url"] == "/api/v1/jobs"
    assert args["params"] == {"a": 1}


def test_should_retry_decisions(write_config):
    """Transport errors retry; retryable statuses retry; others do not."""
    with _client(write_config) as client:
        assert client._should_retry(httpx.ConnectError("x")) is True
        assert client._should_retry(503) is True
        assert client._should_retry(404) is False
        assert client._should_retry(ValueError("nope")) is False

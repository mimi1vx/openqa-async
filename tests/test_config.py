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

"""Tests for configuration parsing and URL/scheme defaulting."""

from openqa_async.client import OpenQAClient


def test_key_secret_resolved_from_server_section(write_config):
    """key/secret are read from the ``[server]`` section and wired up."""
    write_config("[openqa.example.com]\nkey = AAAAAAAA\nsecret = BBBBBBBB\n")
    with OpenQAClient(server="openqa.example.com") as client:
        assert client._apikey == "AAAAAAAA"
        assert client.apisecret == "BBBBBBBB"
        assert client.baseurl == "https://openqa.example.com"
        headers = client._default_headers()
        assert headers["Accept"] == "json"
        assert headers["X-API-Key"] == "AAAAAAAA"


def test_key_secret_resolved_from_baseurl_section(write_config):
    """Falls back to the ``[baseurl]`` section when no server section matches."""
    write_config("[https://openqa.example.com]\nkey = CCCCCCCC\nsecret = DDDDDDDD\n")
    with OpenQAClient(server="openqa.example.com") as client:
        assert client._apikey == "CCCCCCCC"
        assert client.apisecret == "DDDDDDDD"


def test_scheme_defaults_localhost_to_http(write_config):
    """localhost (and loopback) default to non-TLS http."""
    with OpenQAClient(server="localhost") as client:
        assert client.baseurl == "http://localhost"
    with OpenQAClient(server="127.0.0.1") as client:
        assert client.baseurl == "http://127.0.0.1"


def test_scheme_defaults_remote_to_https(write_config):
    """Non-loopback servers default to https."""
    with OpenQAClient(server="openqa.example.com") as client:
        assert client.baseurl == "https://openqa.example.com"


def test_scheme_taken_from_http_prefixed_server(write_config):
    """A ``http://``-prefixed server yields the netloc + that scheme."""
    with OpenQAClient(server="http://openqa.example.com") as client:
        assert client.baseurl == "http://openqa.example.com"


def test_no_key_means_get_only_mode(write_config):
    """With no config, there is no secret and no X-API-Key header."""
    with OpenQAClient(server="openqa.example.com") as client:
        assert client.apisecret == ""
        assert client._apikey == ""
        assert "X-API-Key" not in client._default_headers()


def test_empty_server_defaults_to_first_config_section(write_config):
    """An empty ``server`` falls back to the first section in client.conf."""
    write_config(
        "[openqa.first.com]\nkey = AAAAAAAA\nsecret = BBBBBBBB\n"
        "[openqa.second.com]\nkey = CCCCCCCC\nsecret = DDDDDDDD\n"
    )
    with OpenQAClient(server="") as client:
        assert client.baseurl == "https://openqa.first.com"
        assert client._apikey == "AAAAAAAA"
        assert client.apisecret == "BBBBBBBB"


def test_empty_server_no_config_defaults_to_localhost(write_config):
    """With no config file at all, an empty ``server`` defaults to localhost."""
    # ``write_config`` isolates HOME and strips /etc; not calling it here
    # still leaves discovery hermetic because the fixture is requested.
    with OpenQAClient(server="") as client:
        assert client.baseurl == "http://localhost"
        assert client.apisecret == ""

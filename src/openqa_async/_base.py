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

"""Transport-agnostic base for the openqa_async clients.

``_OpenQAClientBase`` holds everything that does not depend on whether a
request is dispatched synchronously or asynchronously: configuration
parsing, URL/scheme defaulting, default headers, auth construction,
request-argument building, response handling, and retry decision
helpers. The sync and async clients subclass it and supply only the
request/retry loop, which is the one part that genuinely differs between
``httpx.Client`` and ``httpx.AsyncClient``.
"""

import configparser
import logging
import os
import random
import ssl
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import yaml

from ._auth import OpenQAAuth
from .exceptions import RequestError

logger = logging.getLogger(__name__)

#: HTTP status codes that warrant a retry, matching upstream's tuple.
_RETRY_STATUS = frozenset((408, 413, 429, 444, 500, 502, 503, 504, 509, 521, 522, 599))

#: Default timeout for every request; openQA servers are frequently slow,
#: so this is higher than httpx's own 5 s default. ``None`` disables it.
_DEFAULT_TIMEOUT: float | httpx.Timeout | None = 30.0

#: HTTP methods safe to retry after a transport error without risking a
#: double-fired mutation. ``POST`` is deliberately excluded.
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


class _OpenQAClientBase:
    """Shared, transport-agnostic state and helpers for the openQA clients."""

    def __init__(
        self,
        server: str = "",
        scheme: str = "",
        retries: int = 5,
        wait: int = 10,
        verify: bool | str | ssl.SSLContext = True,
        timeout: float | httpx.Timeout | None = _DEFAULT_TIMEOUT,
        retry_methods: frozenset[str] | None = None,
        deadline: float | None = None,
    ) -> None:
        self.retries = retries
        self.wait = wait
        self.verify = verify
        #: Per-request timeout forwarded to the httpx client; ``None`` disables.
        self.timeout = timeout
        #: HTTP methods eligible for transport-error retries (default: the
        #: idempotent set). ``POST`` is excluded so mutations aren't re-sent.
        self.retry_methods = (
            _IDEMPOTENT_METHODS if retry_methods is None else frozenset(retry_methods)
        )
        #: Optional overall wall-clock budget (seconds) for all retries of a
        #: single call; ``None`` means no cap.
        self.deadline = deadline
        #: RNG for jittered backoff; overridable in tests for determinism.
        self._rng = random.Random()

        # Read in config files.
        config = configparser.ConfigParser()
        paths = ("/etc/openqa", f"{os.path.expanduser('~')}/.config/openqa")
        config.read(f"{path}/client.conf" for path in paths)

        # If server not specified, default to the first one in the
        # configuration file. If no configuration file, default to
        # localhost. NOTE: this is different from the perl client, it
        # *always* defaults to localhost.
        if not server:
            try:
                server = config.sections()[0]
            except (configparser.MissingSectionHeaderError, IndexError):
                server = "localhost"

        if server.startswith("http"):
            # Handle entries like [http://foo] or [https://foo]. The
            # perl client does NOT handle these, so you shouldn't use
            # them. This client started out supporting this, though,
            # so it should continue to.
            if not scheme:
                scheme = urlparse(server).scheme
            server = urlparse(server).netloc

        if not scheme:
            if server in ("localhost", "127.0.0.1", "::1"):
                # Default to non-TLS for localhost; cert is unlikely to
                # be valid for 'localhost' and there's no MITM...
                scheme = "http"
            else:
                scheme = "https"

        self.baseurl = urlunparse((scheme, server, "", "", "", ""))

        # Get the API secrets from the config file.
        try:
            apikey = config.get(server, "key")
            self.apisecret = config.get(server, "secret")
        except configparser.Error:
            try:
                apikey = config.get(self.baseurl, "key")
                self.apisecret = config.get(self.baseurl, "secret")
            except configparser.Error:
                logger.debug(
                    "No API key for %s: only GET requests will be allowed", server
                )
                apikey = ""
                self.apisecret = ""

        self._apikey = apikey

    def _default_headers(self) -> dict[str, str]:
        """Static headers applied to every request through the client."""
        headers = {"Accept": "json"}
        if self._apikey:
            headers["X-API-Key"] = self._apikey
        return headers

    def _build_auth(self) -> OpenQAAuth:
        """Build the HMAC auth flow used by both clients."""
        return OpenQAAuth(self.apisecret)

    def _build_request_args(
        self,
        method: str,
        path: str,
        params: Any = None,
        data: Any = None,
        json: Any = None,
    ) -> dict[str, Any]:
        """Return kwargs for ``client.build_request``.

        The path is normalized to a leading slash so it joins predictably
        against the client's ``base_url`` and the signed ``raw_path`` is
        well-defined.
        """
        if not path.startswith("/"):
            path = "/" + path
        return {
            "method": method.upper(),
            "url": path,
            "params": params,
            "data": data,
            "json": json,
        }

    def _handle_response(self, resp: httpx.Response, parse: bool = True) -> Any:
        """Turn an ``httpx.Response`` into parsed output or raise.

        Mirrors upstream branch order: non-2xx raises ``RequestError``;
        ``parse=False`` or a 204 returns the raw response; a ``text/yaml``
        body is loaded with the safe loader; otherwise the JSON body is
        returned.
        """
        if not resp.is_success:
            raise RequestError(
                resp.request.method, str(resp.url), resp.status_code, resp.text
            )
        if not parse or resp.status_code == 204:
            return resp
        # Check if the server sent us YAML when we asked for JSON.
        contype = resp.headers.get("content-type", "")
        if contype.startswith("text/yaml"):
            # SafeLoader is sufficient; we trust the devs not to put
            # anything beyond its capacity in the responses.
            return yaml.safe_load(resp.text)
        return resp.json()

    def _should_retry(self, status_or_exc: int | BaseException) -> bool:
        """Decide whether a status code or exception warrants a retry."""
        if isinstance(status_or_exc, httpx.TransportError):
            return True
        if isinstance(status_or_exc, int):
            return status_or_exc in _RETRY_STATUS
        return False

    def _may_retry_transport(self, method: str, retry_non_idempotent: bool) -> bool:
        """Whether a transport error on ``method`` should be retried."""
        return retry_non_idempotent or method.upper() in self.retry_methods

    def _next_wait(self, wait: int | float) -> int | float:
        """Exponential backoff, capped at 60 seconds (matches upstream)."""
        return min(wait + wait, 60)

    def _backoff(self, wait: int | float) -> float:
        """Full-jitter backoff: a random value in ``[0, min(wait, 60)]``.

        ``wait`` carries the growing exponential base (doubled via
        ``_next_wait`` between attempts); jitter spreads retries to avoid a
        thundering herd. Uses the injectable ``self._rng`` for determinism.
        """
        return self._rng.uniform(0, min(wait, 60))

    def _parse_retry_after(self, resp: httpx.Response) -> float | None:
        """Parse a ``Retry-After`` header into a non-negative delay (seconds).

        Accepts an integer number of seconds or an HTTP-date; returns ``None``
        for a missing or malformed header. Negative/past values clamp to 0.
        """
        value = resp.headers.get("retry-after")
        if value is None:
            return None
        value = value.strip()
        try:
            return max(0.0, float(int(value)))
        except ValueError:
            pass
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())

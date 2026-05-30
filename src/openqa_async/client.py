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

"""Synchronous openQA client built on ``httpx.Client``.

``OpenQAClient`` supplies the one part that genuinely differs between the
sync and async transports: the request/retry loop. Everything else
(configuration, URL/scheme defaulting, headers, auth, response handling,
retry decisions) lives in :class:`~openqa_async._base._OpenQAClientBase`.
"""

import ssl
import time
from types import TracebackType
from typing import Any, Self

import httpx

from ._base import _OpenQAClientBase
from .exceptions import ConnectionError


class OpenQAClient(_OpenQAClientBase):
    """Synchronous client for an openQA server's REST API."""

    def __init__(
        self,
        server: str = "",
        scheme: str = "",
        retries: int = 5,
        wait: int = 10,
        verify: bool | str | ssl.SSLContext = True,
    ) -> None:
        super().__init__(
            server=server,
            scheme=scheme,
            retries=retries,
            wait=wait,
            verify=verify,
        )
        self.client = httpx.Client(
            base_url=self.baseurl,
            headers=self._default_headers(),
            auth=self._build_auth(),
            trust_env=True,
            verify=self.verify,
        )
        #: Legacy alias for ``self.client`` (upstream exposed ``session``).
        self.session = self.client

    def do_request(
        self,
        request: httpx.Request,
        retries: int | None = None,
        wait: int | float | None = None,
        parse: bool = True,
    ) -> Any:
        """Send ``request`` with retry/backoff and return parsed output.

        Retries on the upstream status-code set and on transport errors,
        sleeping with exponential backoff between attempts. A status code
        of ``retries`` means up to that many *retries* (so ``retries + 1``
        total attempts). After the attempts are exhausted, a transport
        failure raises :class:`~openqa_async.exceptions.ConnectionError`
        and a non-2xx response raises
        :class:`~openqa_async.exceptions.RequestError` (via
        ``_handle_response``).
        """
        if retries is None:
            retries = self.retries
        if wait is None:
            wait = self.wait

        for attempt in range(retries + 1):
            last_attempt = attempt == retries
            try:
                resp = self.client.send(request)
            except httpx.TransportError as exc:
                if last_attempt:
                    raise ConnectionError(
                        f"Connection to {request.url} failed: {exc}"
                    ) from exc
                time.sleep(wait)
                wait = self._next_wait(wait)
                continue

            if not last_attempt and self._should_retry(resp.status_code):
                time.sleep(wait)
                wait = self._next_wait(wait)
                continue

            return self._handle_response(resp, parse)

    def openqa_request(
        self,
        method: str,
        path: str,
        params: Any = None,
        retries: int | None = None,
        wait: int | float | None = None,
        data: Any = None,
        json: Any = None,
    ) -> Any:
        """Build and dispatch a request against the openQA API."""
        args = self._build_request_args(method, path, params, data, json)
        request = self.client.build_request(**args)
        return self.do_request(request, retries=retries, wait=wait, parse=True)

    def close(self) -> None:
        """Close the underlying ``httpx.Client``."""
        self.client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

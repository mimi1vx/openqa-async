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

"""Asynchronous openQA client built on ``httpx.AsyncClient``.

``AsyncOpenQAClient`` is the async mirror of
:class:`~openqa_async.client.OpenQAClient`. It supplies the one part that
genuinely differs between the sync and async transports: the
request/retry loop (here awaiting ``send`` and sleeping via
``asyncio.sleep``). Everything else (configuration, URL/scheme
defaulting, headers, auth, response handling, retry decisions) lives in
:class:`~openqa_async._base._OpenQAClientBase`.
"""

import asyncio
import ssl
from types import TracebackType
from typing import Any, Self

import httpx

from ._base import _OpenQAClientBase
from .exceptions import ConnectionError


class AsyncOpenQAClient(_OpenQAClientBase):
    """Asynchronous client for an openQA server's REST API."""

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
        self.client = httpx.AsyncClient(
            base_url=self.baseurl,
            headers=self._default_headers(),
            auth=self._build_auth(),
            trust_env=True,
            verify=self.verify,
        )

    async def do_request(
        self,
        request: httpx.Request,
        retries: int | None = None,
        wait: int | float | None = None,
        parse: bool = True,
    ) -> Any:
        """Send ``request`` with retry/backoff and return parsed output.

        Retries on the upstream status-code set and on transport errors,
        sleeping with exponential backoff between attempts. A value of
        ``retries`` means up to that many *retries* (so ``retries + 1``
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
                resp = await self.client.send(request)
            except httpx.TransportError as exc:
                if last_attempt:
                    raise ConnectionError(
                        f"Connection to {request.url} failed: {exc}"
                    ) from exc
                await asyncio.sleep(wait)
                wait = self._next_wait(wait)
                continue

            if not last_attempt and self._should_retry(resp.status_code):
                await asyncio.sleep(wait)
                wait = self._next_wait(wait)
                continue

            return self._handle_response(resp, parse)

    async def openqa_request(
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
        return await self.do_request(request, retries=retries, wait=wait, parse=True)

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient``."""
        await self.client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

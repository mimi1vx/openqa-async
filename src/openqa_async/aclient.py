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
from time import monotonic
from types import TracebackType
from typing import Any, Self

import httpx

from ._base import _DEFAULT_TIMEOUT, _OpenQAClientBase
from .exceptions import ConnectionError


class AsyncOpenQAClient(_OpenQAClientBase):
    """Asynchronous client for an openQA server's REST API.

    ``timeout`` is the per-request timeout forwarded to the underlying
    ``httpx.AsyncClient`` (default 30 s; ``None`` disables). ``retry_methods``
    restricts which HTTP methods are retried on transport errors (default: the
    idempotent set, so ``POST`` mutations are not re-sent). ``deadline`` bounds
    the total wall-clock time spent retrying a single call.
    """

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
        super().__init__(
            server=server,
            scheme=scheme,
            retries=retries,
            wait=wait,
            verify=verify,
            timeout=timeout,
            retry_methods=retry_methods,
            deadline=deadline,
        )
        self.client = httpx.AsyncClient(
            base_url=self.baseurl,
            headers=self._default_headers(),
            auth=self._build_auth(),
            trust_env=True,
            verify=self.verify,
            timeout=self.timeout,
        )

    async def do_request(
        self,
        request: httpx.Request,
        retries: int | None = None,
        wait: int | float | None = None,
        parse: bool = True,
        retry_non_idempotent: bool = False,
        deadline: float | None = None,
    ) -> Any:
        """Send ``request`` with retry/backoff and return parsed output.

        Retries on the upstream status-code set and on transport errors,
        sleeping with jittered exponential backoff between attempts. A value of
        ``retries`` means up to that many *retries* (so ``retries + 1`` total
        attempts). Transport errors are only retried for idempotent methods
        unless ``retry_non_idempotent`` is set, so a ``POST`` that fails
        mid-flight is not re-sent. When the server returns a retryable status
        with a ``Retry-After`` header, that guidance is honoured (bounded by
        ``deadline``). ``deadline`` (seconds) caps the total time spent
        retrying; on expiry the last error is raised.

        After the attempts are exhausted, a transport failure raises
        :class:`~openqa_async.exceptions.ConnectionError` and a non-2xx
        response raises :class:`~openqa_async.exceptions.RequestError` (via
        ``_handle_response``).
        """
        if retries is None:
            retries = self.retries
        if wait is None:
            wait = self.wait
        if deadline is None:
            deadline = self.deadline
        retries = max(retries, 0)
        method = request.method
        start = monotonic()

        for attempt in range(retries + 1):
            last_attempt = attempt == retries
            try:
                resp = await self.client.send(request)
            except httpx.TransportError as exc:
                may_retry = self._may_retry_transport(method, retry_non_idempotent)
                if last_attempt or not may_retry:
                    raise ConnectionError(
                        f"Connection to {request.url} failed: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                if not await self._sleep_backoff(wait, start, deadline):
                    raise ConnectionError(
                        f"Connection to {request.url} failed: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                wait = self._next_wait(wait)
                continue

            if not last_attempt and self._should_retry(resp.status_code):
                retry_after = self._parse_retry_after(resp)
                sleep_for = self._backoff(wait)
                if retry_after is not None:
                    sleep_for = max(retry_after, sleep_for)
                if not await self._sleep_within_deadline(sleep_for, start, deadline):
                    return self._handle_response(resp, parse)
                wait = self._next_wait(wait)
                continue

            return self._handle_response(resp, parse)

        # Unreachable in practice (loop always returns/raises above), but
        # guards against future edits and non-positive ``retries``.
        raise ConnectionError(f"Connection to {request.url} failed: no attempts made")

    async def _sleep_backoff(
        self, wait: int | float, start: float, deadline: float | None
    ) -> bool:
        """Sleep a jittered backoff; return ``False`` if it would blow the deadline."""
        return await self._sleep_within_deadline(self._backoff(wait), start, deadline)

    async def _sleep_within_deadline(
        self, sleep_for: float, start: float, deadline: float | None
    ) -> bool:
        """Sleep ``sleep_for`` unless it would exceed ``deadline``.

        Returns ``True`` if it slept, ``False`` if the deadline would be
        exceeded (caller should then stop retrying).
        """
        if deadline is not None and (monotonic() - start) + sleep_for > deadline:
            return False
        await asyncio.sleep(sleep_for)
        return True

    async def openqa_request(
        self,
        method: str,
        path: str,
        params: Any = None,
        retries: int | None = None,
        wait: int | float | None = None,
        data: Any = None,
        json: Any = None,
        retry_non_idempotent: bool = False,
        deadline: float | None = None,
    ) -> Any:
        """Build and dispatch a request against the openQA API."""
        args = self._build_request_args(method, path, params, data, json)
        request = self.client.build_request(**args)
        return await self.do_request(
            request,
            retries=retries,
            wait=wait,
            parse=True,
            retry_non_idempotent=retry_non_idempotent,
            deadline=deadline,
        )

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

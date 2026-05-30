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

"""HMAC authentication for the openqa_async client library.

A single ``httpx.Auth`` subclass drives request signing for both the
synchronous and asynchronous clients.
"""

import hmac
import time
from hashlib import sha1

import httpx


class OpenQAAuth(httpx.Auth):
    """Sign requests with openQA's HMAC-SHA1 scheme.

    The signed string is the request ``raw_path`` (path plus ``?query``)
    concatenated with the current ``str(time.time())`` timestamp, with the
    ``%20``->``+`` and ``~``->``%7E`` fixups applied to match upstream's
    ``requests``-based ``path_url`` signing byte-for-byte.

    The ``X-API-Key`` header is a static client header set by the base
    client, not here.
    """

    def __init__(self, apisecret: str | None) -> None:
        self.apisecret = apisecret

    def auth_flow(self, request: httpx.Request):
        if not self.apisecret:
            # GET works without auth; nothing to sign.
            yield request
            return

        path = (
            request.url.raw_path.decode("ascii").replace("%20", "+").replace("~", "%7E")
        )
        ts = str(time.time())
        apihash = hmac.new(
            self.apisecret.encode("utf-8"),
            f"{path}{ts}".encode("utf-8"),
            sha1,
        ).hexdigest()
        request.headers["X-API-Microtime"] = ts
        request.headers["X-API-Hash"] = apihash
        yield request

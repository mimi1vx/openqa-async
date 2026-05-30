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

"""openqa_async: an httpx-based openQA client with sync and async APIs.

The pythonic entry points are :class:`OpenQAClient` (synchronous) and
:class:`AsyncOpenQAClient` (asynchronous). ``OpenQA_Client`` is a thin
compatibility alias for the synchronous client so legacy code that calls
``OpenQA_Client(...).openqa_request(...)`` mostly keeps working.
"""

from . import const
from .aclient import AsyncOpenQAClient
from .client import OpenQAClient
from .exceptions import ConnectionError, OpenQAClientError, RequestError

#: Compatibility alias for the upstream ``requests``-based class name.
OpenQA_Client = OpenQAClient

__all__ = [
    "AsyncOpenQAClient",
    "ConnectionError",
    "OpenQAClient",
    "OpenQA_Client",
    "OpenQAClientError",
    "RequestError",
    "const",
]

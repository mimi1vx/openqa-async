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

"""Exceptions for the openqa_async client library."""


class OpenQAClientError(Exception):
    """Base class for all openqa_async client errors."""


class RequestError(OpenQAClientError):
    """Error raised when a request fails (after retries). Stores the
    request method, URL, the final HTTP status code, and the response
    text.
    """

    def __init__(self, method: str, url: str, status_code: int, text: str) -> None:
        super().__init__(method, url, status_code, text)
        self.method = method
        self.url = url
        self.status_code = status_code
        self.text = text


class ConnectionError(OpenQAClientError):
    """Error raised when the server connection fails. Wraps the
    underlying httpx transport error.
    """

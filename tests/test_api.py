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

"""Tests for the public API surface of :mod:`openqa_async`."""

import openqa_async


def test_public_names_importable():
    from openqa_async import (  # noqa: F401
        AsyncOpenQAClient,
        ConnectionError,
        OpenQA_Client,
        OpenQAClient,
        OpenQAClientError,
        RequestError,
        const,
    )


def test_openqa_client_alias_identity():
    assert openqa_async.OpenQA_Client is openqa_async.OpenQAClient


def test_exception_hierarchy():
    assert issubclass(openqa_async.RequestError, openqa_async.OpenQAClientError)
    assert issubclass(openqa_async.ConnectionError, openqa_async.OpenQAClientError)


def test_all_names_resolve():
    for name in openqa_async.__all__:
        assert hasattr(openqa_async, name), name

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

"""Shared fixtures for the openqa_async test suite."""

import configparser
import os

import pytest


@pytest.fixture
def write_config(tmp_path, monkeypatch):
    """Hermetically isolate ``client.conf`` discovery.

    The base client reads both ``/etc/openqa/client.conf`` and
    ``~/.config/openqa/client.conf``. This fixture:

    * points ``os.path.expanduser('~')`` at a throwaway ``tmp_path`` HOME,
      and
    * wraps ``configparser.ConfigParser.read`` so the hardcoded
      ``/etc/openqa`` entry is dropped before any real system file can be
      read.

    It returns a callable that writes the given INI text to the temp HOME's
    ``.config/openqa/client.conf`` (creating parent dirs).
    """
    monkeypatch.setattr(os.path, "expanduser", lambda _path: str(tmp_path))

    real_read = configparser.ConfigParser.read

    def filtered_read(self, filenames, encoding=None):
        # ``filenames`` may be a generator; materialise and strip /etc.
        kept = [name for name in filenames if not str(name).startswith("/etc/openqa")]
        return real_read(self, kept, encoding=encoding)

    monkeypatch.setattr(configparser.ConfigParser, "read", filtered_read)

    def _write(text: str) -> str:
        confdir = tmp_path / ".config" / "openqa"
        confdir.mkdir(parents=True, exist_ok=True)
        conffile = confdir / "client.conf"
        conffile.write_text(text)
        return str(conffile)

    return _write

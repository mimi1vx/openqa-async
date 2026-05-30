# openqa-async

An [httpx](https://www.python-httpx.org/)-based client for the
[openQA](https://open.qa/) REST API, exposing both a **synchronous** and an
**asynchronous** API. It is a port of
[`openQA-python-client`](https://github.com/os-autoinst/openQA-python-client)
from `requests` to `httpx`, preserving its HMAC request signing, `client.conf`
discovery, and YAML-response fallback.

## Installation

```sh
uv add openqa-async
# or
pip install openqa-async
```

## Usage

### Synchronous

```python
from openqa_async import OpenQAClient

with OpenQAClient(server="openqa.opensuse.org") as client:
    jobs = client.openqa_request("GET", "/api/v1/jobs", params={"limit": 10})
    print(jobs)
```

### Asynchronous

```python
import asyncio

from openqa_async import AsyncOpenQAClient


async def main():
    async with AsyncOpenQAClient(server="openqa.opensuse.org") as client:
        jobs = await client.openqa_request(
            "GET", "/api/v1/jobs", params={"limit": 10}
        )
        print(jobs)


asyncio.run(main())
```

### `openqa_request` signature

Both clients share the same request method (the async one is awaitable):

```python
openqa_request(
    method,            # "GET", "POST", ...
    path,              # e.g. "/api/v1/jobs" (a leading slash is optional)
    params=None,       # query-string parameters
    retries=None,      # override the client default (5)
    wait=None,         # override the initial backoff in seconds (10)
    data=None,         # form-encoded body
    json=None,         # JSON body
)
```

Responses are parsed automatically: a `text/yaml` body is loaded with
`yaml.safe_load`, a `204 No Content` (or `parse=False`) returns the raw
`httpx.Response`, and everything else is decoded as JSON. Non-2xx responses
raise `RequestError`; transport failures raise `ConnectionError`. Retryable
status codes (e.g. `503`) are retried with exponential backoff.

## Configuration

Credentials are read from INI-style `client.conf` files, searched in order:

1. `/etc/openqa/client.conf`
2. `~/.config/openqa/client.conf`

Each section is keyed by the server host (or full base URL) and provides the
API `key`/`secret`:

```ini
[openqa.opensuse.org]
key = YOUR_API_KEY
secret = YOUR_API_SECRET
```

The lookup tries the bare `server` section first, then the full base URL
section. When a key/secret is present, requests are HMAC-SHA1 signed and the
`X-API-Key` header is sent. Without credentials only unauthenticated `GET`
requests are possible.

**Scheme defaulting:** the scheme defaults to `https`, except for loopback
hosts (`localhost`, `127.0.0.1`, `::1`), which default to `http`. You can also
pass a fully-qualified server such as `http://openqa.example.com`.

## Migration from `openQA-python-client`

For code written against the upstream `requests`-based client, a compatibility
alias keeps most call sites working unchanged:

```python
from openqa_async import OpenQA_Client  # alias for OpenQAClient

client = OpenQA_Client(server="openqa.opensuse.org")
jobs = client.openqa_request("GET", "/api/v1/jobs")
```

`OpenQA_Client` is the synchronous `OpenQAClient`, and `openqa_request` keeps
the same method/path semantics. New code should prefer `OpenQAClient` /
`AsyncOpenQAClient` directly.

## Disabling TLS verification

Both clients accept a `verify` parameter (default `True`) that is passed
straight through to httpx. It accepts a `bool`, a CA-bundle path, or an
`ssl.SSLContext`:

```python
# Self-signed or internal-CA openQA instance:
client = OpenQAClient(server="openqa.internal", verify="/path/to/internal-ca.pem")

# Disable verification entirely:
client = OpenQAClient(server="openqa.internal", verify=False)
```

> **Security warning:** `verify=False` disables TLS certificate verification
> and exposes the connection to man-in-the-middle attacks. Use it only against
> trusted instances on trusted networks; prefer supplying the internal CA
> bundle instead.

## License

GPL-2.0-or-later. See [COPYING](COPYING).

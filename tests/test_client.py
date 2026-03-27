"""Tests for pyhomecast client."""

from unittest.mock import MagicMock

from pyhomecast import HomecastClient


def _make_client(api_url=None):
    """Create a client with a mock session."""
    session = MagicMock()
    kwargs = {}
    if api_url:
        kwargs["api_url"] = api_url
    return HomecastClient(session, **kwargs)


def test_default_api_url():
    client = _make_client()
    assert client._api_url == "https://api.homecast.cloud"


def test_custom_api_url():
    client = _make_client(api_url="https://staging.api.homecast.cloud")
    assert client._api_url == "https://staging.api.homecast.cloud"


def test_custom_api_url_strips_trailing_slash():
    client = _make_client(api_url="https://api.homecast.cloud/")
    assert client._api_url == "https://api.homecast.cloud"


def test_authenticate():
    client = _make_client()
    assert client._token is None
    client.authenticate("test-token")
    assert client._token == "test-token"


def test_headers_with_token():
    client = _make_client()
    client.authenticate("my-token")
    headers = client._headers
    assert headers["Authorization"] == "Bearer my-token"
    assert headers["Content-Type"] == "application/json"


def test_headers_without_token():
    client = _make_client()
    headers = client._headers
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"

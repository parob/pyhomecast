"""Async client for the Homecast REST API."""

from __future__ import annotations

from typing import Any

import aiohttp

from .exceptions import HomecastAuthError, HomecastConnectionError, HomecastError
from .models import HomecastState

DEFAULT_API_URL = "https://api.homecast.cloud"


class HomecastClient:
    """Async client for the Homecast REST API.

    Args:
        session: An aiohttp ClientSession (caller manages its lifecycle).
        api_url: Base URL of the Homecast API.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str = DEFAULT_API_URL,
    ) -> None:
        self._session = session
        self._api_url = api_url.rstrip("/")
        self._token: str | None = None

    def authenticate(self, token: str) -> None:
        """Set the Bearer token for API requests."""
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an authenticated API request."""
        url = f"{self._api_url}{path}"
        try:
            async with self._session.request(
                method, url, headers=self._headers, **kwargs
            ) as resp:
                if resp.status in (401, 403):
                    text = await resp.text()
                    raise HomecastAuthError(
                        f"Authentication failed: {text}", status=resp.status
                    )
                if resp.status >= 500:
                    text = await resp.text()
                    raise HomecastConnectionError(
                        f"Server error {resp.status}: {text}", status=resp.status
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise HomecastError(
                        f"API error {resp.status}: {text}", status=resp.status
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise HomecastConnectionError(f"Connection error: {err}") from err

    async def get_state(
        self,
        home: str | None = None,
        room: str | None = None,
        device_type: str | None = None,
        name: str | None = None,
    ) -> HomecastState:
        """Fetch current state of all homes/accessories.

        Returns a parsed HomecastState object.
        """
        params: dict[str, str] = {}
        if home:
            params["home"] = home
        if room:
            params["room"] = room
        if device_type:
            params["type"] = device_type
        if name:
            params["name"] = name

        raw = await self._request("GET", "/rest/state", params=params)
        return HomecastState.from_api_response(raw)

    async def get_state_raw(
        self,
        home: str | None = None,
        room: str | None = None,
        device_type: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Fetch current state as raw JSON (unparsed)."""
        params: dict[str, str] = {}
        if home:
            params["home"] = home
        if room:
            params["room"] = room
        if device_type:
            params["type"] = device_type
        if name:
            params["name"] = name

        return await self._request("GET", "/rest/state", params=params)

    async def set_state(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Set state of one or more accessories.

        Args:
            updates: Nested dict {home_key: {room_key: {accessory_key: {prop: value}}}}

        Returns the API response.
        """
        return await self._request("POST", "/rest/state", json=updates)

    async def run_scene(self, home: str, name: str) -> dict[str, Any]:
        """Execute a scene by name.

        Args:
            home: Home key (e.g. 'my_home_0bf8').
            name: Scene name (case-insensitive).
        """
        return await self._request(
            "POST", "/rest/scene", json={"home": home, "name": name}
        )

    async def register_client(
        self,
        redirect_uri: str,
        client_name: str = "Home Assistant",
    ) -> dict[str, Any]:
        """Dynamically register an OAuth client (RFC 7591).

        Returns: {"client_id": ..., "client_secret": ..., ...}
        """
        return await self._request(
            "POST",
            "/oauth/register",
            json={
                "redirect_uris": [redirect_uri],
                "client_name": client_name,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "mcp:read mcp:write",
                "token_endpoint_auth_method": "client_secret_post",
            },
        )

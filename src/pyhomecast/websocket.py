"""WebSocket client for real-time state updates from Homecast."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import aiohttp

from .client import DEFAULT_API_URL
from .exceptions import HomecastAuthError, HomecastConnectionError

_LOGGER = logging.getLogger(__name__)

_PING_INTERVAL = 30
_RENEW_INTERVAL = 240  # 80% of 300s TTL
_SUBSCRIPTION_TTL = 300
_MAX_RECONNECT_DELAY = 60
_BROADCAST_TYPES = frozenset({
    "characteristic_update",
    "reachability_update",
    "service_group_update",
    "relay_status_update",
})


class HomecastWebSocket:
    """WebSocket client for receiving real-time state updates from Homecast.

    Connects to the Homecast WebSocket endpoint, subscribes to home updates,
    and invokes a callback on each broadcast message. Handles auto-reconnect,
    ping/pong keepalive, and subscription renewal.

    Args:
        session: An aiohttp ClientSession (caller manages its lifecycle).
        api_url: Base URL of the Homecast API (https scheme).
        device_id: Persistent device identifier for this connection.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str = DEFAULT_API_URL,
        device_id: str = "",
        community: bool = False,
    ) -> None:
        self._session = session
        self._api_url = api_url.rstrip("/")
        self._device_id = device_id or f"ha_{uuid.uuid4().hex[:12]}"
        self._token: str | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._callback: Callable[[dict[str, Any]], None] | None = None
        self._subscribed_homes: list[str] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._closing = False
        self._reconnect_delay = 1.0
        self._community = community

    @property
    def connected(self) -> bool:
        """Return True if the WebSocket is connected."""
        return self._ws is not None and not self._ws.closed

    def set_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback for broadcast messages."""
        self._callback = callback

    def set_token(self, token: str) -> None:
        """Update the auth token (used on next reconnect)."""
        self._token = token

    async def connect(self, token: str) -> None:
        """Connect to the Homecast WebSocket.

        Args:
            token: OAuth2 access token for authentication.

        Raises:
            HomecastAuthError: If the server rejects the token.
            HomecastConnectionError: If the connection cannot be established.
        """
        self._token = token
        self._closing = False
        await self._connect()

    async def _connect(self) -> None:
        """Internal connect — establishes the WebSocket and starts background tasks."""
        ws_url = self._build_ws_url()
        try:
            self._ws = await self._session.ws_connect(
                ws_url,
                heartbeat=None,  # We handle pings ourselves
            )
        except aiohttp.WSServerHandshakeError as err:
            if err.status in (401, 403):
                raise HomecastAuthError(
                    f"WebSocket auth failed: {err}", status=err.status
                ) from err
            raise HomecastConnectionError(
                f"WebSocket handshake failed: {err}"
            ) from err
        except (aiohttp.ClientError, OSError) as err:
            raise HomecastConnectionError(
                f"WebSocket connection failed: {err}"
            ) from err

        self._reconnect_delay = 1.0
        _LOGGER.info("WebSocket connected to %s", self._api_url)

        # Community mode: authenticate via protocol message
        if self._community and self._token:
            await self._send({
                "id": str(uuid.uuid4()),
                "type": "request",
                "action": "authenticate",
                "payload": {"token": self._token},
            })

        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._message_loop()),
            asyncio.create_task(self._ping_loop()),
        ]

    async def disconnect(self) -> None:
        """Disconnect the WebSocket and cancel background tasks."""
        self._closing = True
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        _LOGGER.info("WebSocket disconnected")

    async def subscribe(self, home_keys: list[str]) -> None:
        """Subscribe to state updates for the given homes.

        Args:
            home_keys: List of home slug keys (e.g. ["my_home_0bf8"]).
        """
        if not self.connected:
            self._subscribed_homes = home_keys
            return

        self._subscribed_homes = home_keys
        scopes = [{"type": "home", "id": key} for key in home_keys]
        msg = {
            "type": "request",
            "id": str(uuid.uuid4()),
            "action": "subscribe",
            "payload": {"scopes": scopes, "ttl": _SUBSCRIPTION_TTL},
        }
        await self._send(msg)
        _LOGGER.debug("Subscribed to %d home(s): %s", len(home_keys), home_keys)

        # Start renewal task if not already running
        if not any(t for t in self._tasks if not t.done() and t.get_name() == "renew"):
            task = asyncio.create_task(self._renew_loop())
            task.set_name("renew")
            self._tasks.append(task)

    async def _send(self, msg: dict[str, Any]) -> None:
        """Send a JSON message on the WebSocket."""
        if self._ws and not self._ws.closed:
            await self._ws.send_json(msg)

    async def _message_loop(self) -> None:
        """Receive messages from the WebSocket."""
        try:
            async for msg in self._ws:  # type: ignore[union-attr]
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.json())
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.exception("WebSocket message loop error")

        if not self._closing:
            asyncio.create_task(self._auto_reconnect())

    def _handle_message(self, data: dict[str, Any]) -> None:
        """Process a single incoming message."""
        msg_type = data.get("type", "")
        _LOGGER.debug("WS recv: type=%s keys=%s", msg_type, list(data.keys())[:5])

        if msg_type == "ping":
            asyncio.create_task(self._send({"type": "pong"}))
            return

        if msg_type == "pong":
            return

        if msg_type == "reconnect":
            _LOGGER.info("Server requested reconnect")
            asyncio.create_task(self._reconnect())
            return

        if msg_type == "config":
            return

        # Forward broadcasts to callback
        if msg_type in _BROADCAST_TYPES:
            if self._callback:
                _LOGGER.debug("Forwarding %s to callback", msg_type)
                self._callback(data)
            else:
                _LOGGER.warning("Broadcast %s received but no callback set!", msg_type)

    async def _ping_loop(self) -> None:
        """Send periodic pings to keep the session alive."""
        try:
            while True:
                await asyncio.sleep(_PING_INTERVAL)
                await self._send({"type": "ping"})
        except asyncio.CancelledError:
            return

    async def _renew_loop(self) -> None:
        """Periodically renew subscriptions before they expire."""
        try:
            while True:
                await asyncio.sleep(_RENEW_INTERVAL)
                if self._subscribed_homes and self.connected:
                    await self.subscribe(self._subscribed_homes)
        except asyncio.CancelledError:
            return

    async def _reconnect(self) -> None:
        """Graceful reconnect (e.g. after server sends 'reconnect')."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        await self._auto_reconnect()

    async def _auto_reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        if self._closing or not self._token:
            return

        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        while not self._closing:
            _LOGGER.info(
                "Reconnecting in %.0fs...", self._reconnect_delay
            )
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(
                self._reconnect_delay * 2, _MAX_RECONNECT_DELAY
            )

            try:
                await self._connect()
                # Re-subscribe after reconnect
                if self._subscribed_homes:
                    await self.subscribe(self._subscribed_homes)
                return
            except (HomecastAuthError, HomecastConnectionError) as err:
                _LOGGER.warning("Reconnect failed: %s", err)
            except Exception:
                _LOGGER.exception("Unexpected reconnect error")

    def _build_ws_url(self) -> str:
        """Build the WebSocket URL with query parameters."""
        parsed = urlparse(self._api_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"

        if self._community:
            # Community mode: WS runs on HTTP port + 1, no path or query params
            host = parsed.hostname or "localhost"
            port = (parsed.port or 5656) + 1
            return f"{ws_scheme}://{host}:{port}"

        params = urlencode({
            "token": self._token or "",
            "device_id": self._device_id,
            "client_type": "homeassistant",
            "device_name": "Home Assistant",
        })
        return urlunparse((
            ws_scheme,
            parsed.netloc,
            "/ws",
            "",
            params,
            "",
        ))

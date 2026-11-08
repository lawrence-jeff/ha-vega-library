"""Small async client for the Vega Discover (Innovative / III) patron API.

This is an unofficial client for the same endpoints the library's own website uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .const import STATUS_FROZEN, STATUS_IN_TRANSIT, STATUS_READY, STATUS_WAITING

_LOGGER = logging.getLogger(__name__)

CLIENT_ID = "convergence"
ISSUES_URL = "https://github.com/lawrence-jeff/ha-vega-library/issues"
# Status codes seen so far: "0" waiting, "b" ready, "t" in transit.
KNOWN_STATUS_CODES = {"0", "b", "t"}
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
# Refresh a little before the access token really expires.
EXPIRY_SKEW = 60


class VegaError(Exception):
    """Base error."""


class VegaAuthError(VegaError):
    """The library rejected the credentials."""


class VegaConnectionError(VegaError):
    """The library could not be reached or returned something unexpected."""


class VegaUnknownLibraryError(VegaError):
    """The library ID / host combination does not exist."""


@dataclass(frozen=True)
class Discovery:
    """What we learn from a library's Vega catalog address."""

    site_code: str  # e.g. "slouc"; also the library ID used in headers and the auth realm
    host: str  # Vega API host, e.g. "na2.iiivega.com"
    auth_url: str  # Keycloak base URL, e.g. "https://auth.na2.iiivega.com/auth"
    site_host: str  # host the catalog is served from (may be a vanity domain)


async def async_discover(session: aiohttp.ClientSession, address: str) -> Discovery:
    """Work out the library ID and Vega host from a library's catalog address.

    Every Vega site serves ``/lookup`` (plain text site code) and ``/config.js``
    (API and Keycloak URLs); the Vega web app itself reads both on startup.
    """
    address = address.strip()
    if "//" not in address:
        address = f"https://{address}"
    parsed = urlparse(address)
    if parsed.scheme != "https" or not parsed.hostname:
        _LOGGER.warning("Vega discovery: %r is not an https address", address)
        raise VegaUnknownLibraryError(address)
    origin = f"https://{parsed.netloc}"
    _LOGGER.debug("Vega discovery: checking %s", origin)
    try:
        async with session.get(f"{origin}/lookup", timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                _LOGGER.warning("Vega discovery: %s/lookup returned HTTP %s", origin, resp.status)
                raise VegaUnknownLibraryError(f"{origin}/lookup returned {resp.status}")
            code = (await resp.text()).strip().lower()
        async with session.get(f"{origin}/config.js", timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                _LOGGER.warning("Vega discovery: %s/config.js returned HTTP %s", origin, resp.status)
                raise VegaUnknownLibraryError(f"{origin}/config.js returned {resp.status}")
            config_js = await resp.text()
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.warning("Vega discovery: could not reach %s: %s", origin, err)
        raise VegaConnectionError(f"discovery: {err}") from err

    api_url = re.search(r"var API_URL\s*=\s*'([^']+)'", config_js)
    if not re.fullmatch(r"[a-z0-9-]+", code) or not api_url:
        _LOGGER.warning(
            "Vega discovery: %s does not look like a Vega site (lookup returned %d chars, API_URL %s)",
            origin,
            len(code),
            "found" if api_url else "missing",
        )
        raise VegaUnknownLibraryError(f"{origin} does not look like a Vega site")
    host = re.sub(r"^https?://", "", api_url.group(1)).rstrip("/").lower()
    keycloak = re.search(r"var KEYCLOAK_URL\s*=\s*'([^']+)'", config_js)
    auth_url = (
        keycloak.group(1).replace(":443", "").rstrip("/") if keycloak else f"https://auth.{host}/auth"
    )
    _LOGGER.debug(
        "Vega discovery: site code %s, host %s, auth %s, served from %s",
        code,
        host,
        auth_url,
        parsed.netloc.lower(),
    )
    return Discovery(code, host, auth_url, parsed.netloc.lower())


@dataclass(frozen=True)
class Hold:
    """A single hold on the patron's account."""

    id: str
    title: str
    author: str | None
    vendor: str | None
    status: str | None
    priority: int
    queue_length: int | None
    frozen: bool
    expires: datetime | None
    cover_url: str | None
    cover_url_large: str | None = None

    @property
    def status_name(self) -> str:
        """ready / in_transit / waiting / frozen.

        Observed library codes: "b" = ready on the shelf, "t" = in transit, "0" = waiting.
        Queue position 0 also means ready, which covers digital holds whose status code
        has not been seen. Unknown codes fall back to "waiting".
        """
        if self.frozen:
            return STATUS_FROZEN
        if self.status == "b" or self.priority == 0:
            return STATUS_READY
        if self.status == "t":
            return STATUS_IN_TRANSIT
        return STATUS_WAITING

    @property
    def ready(self) -> bool:
        """True when the hold is waiting for pickup."""
        return self.status_name == STATUS_READY

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly form used in sensor attributes and events."""
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "status": self.status_name,
            "position": self.priority,
            "queue_length": self.queue_length,
            "vendor": self.vendor,
            "frozen": self.frozen,
            "pickup_by": self.expires.isoformat() if self.expires else None,
            "cover_url": self.cover_url,
            "cover_url_large": self.cover_url_large,
        }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_hold(item: dict[str, Any]) -> Hold:
    """Turn one raw API item into a Hold."""
    resource = item.get("resource") or {}
    cover = resource.get("coverUrl") or {}
    agent = resource.get("primaryAgent") or {}
    return Hold(
        id=str(item.get("id")),
        title=resource.get("title") or "Unknown title",
        author=(agent.get("label") or "").rstrip(".") or None,
        vendor=item.get("vendor"),
        status=item.get("status"),
        priority=int(item.get("priority", -1)),
        queue_length=item.get("priorityQueueLength"),
        frozen=bool(item.get("frozen")),
        expires=_parse_dt(item.get("expirationDate")),
        cover_url=cover.get("medium") or cover.get("large") or cover.get("small"),
        cover_url_large=cover.get("large"),
    )


class VegaClient:
    """Talks to one library's Vega instance."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        site_code: str,
        host: str,
        username: str,
        pin: str,
        *,
        auth_url: str | None = None,
        site_host: str | None = None,
        refresh_token: str | None = None,
        token_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._pin = pin
        self._refresh_token = refresh_token
        self._token_callback = token_callback
        self._access_token: str | None = None
        self._access_expires = 0.0
        # The Vega web app derives the Keycloak realm from the site code,
        # dropping any "prefix-" before the last hyphen.
        realm = re.sub(r"^[^.]*-", "", site_code.split(".")[0])
        base = (auth_url or f"https://auth.{host}/auth").rstrip("/")
        self._token_url = f"{base}/realms/{realm}/protocol/openid-connect/token"
        self._holds_url = f"https://{host}/api/search-result/patrons/me/holds"
        self._domain = f"{site_code}.{host}"
        self._host_domain = site_host or self._domain
        self._warned_codes: set[str | None] = set()
        _LOGGER.debug("Vega client for %s (token endpoint %s)", self._domain, self._token_url)

    async def _token_request(self, form: dict[str, str]) -> None:
        """POST to the token endpoint and store the result."""
        grant = form["grant_type"]
        form = {"client_id": CLIENT_ID, **form}
        _LOGGER.debug("Requesting %s token", grant)
        try:
            async with self._session.post(
                self._token_url, data=form, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 404:
                    _LOGGER.warning("Token endpoint %s returned 404 (wrong library?)", self._token_url)
                    raise VegaUnknownLibraryError(self._token_url)
                if resp.status in (400, 401):
                    _LOGGER.debug("%s token request rejected: HTTP %s", grant, resp.status)
                    raise VegaAuthError(f"{grant} token request rejected (HTTP {resp.status})")
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise VegaConnectionError(f"{grant} token request failed: {err!r}") from err

        token = data.get("access_token")
        if not token:
            raise VegaConnectionError(
                f"{grant} token response had no access_token (keys: {sorted(data)})"
            )
        _LOGGER.debug(
            "Got %s token (expires in %ss, new refresh token: %s)",
            grant,
            data.get("expires_in"),
            bool(data.get("refresh_token")),
        )
        self._access_token = token
        self._access_expires = time.monotonic() + int(data.get("expires_in", 300)) - EXPIRY_SKEW
        if new_refresh := data.get("refresh_token"):
            self._refresh_token = new_refresh
            if self._token_callback:
                self._token_callback(new_refresh)

    async def async_login(self) -> None:
        """Get a fresh access token, preferring the refresh token over the PIN."""
        if self._refresh_token:
            try:
                await self._token_request(
                    {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
                )
                return
            except VegaAuthError:
                _LOGGER.debug("Refresh token rejected, signing in with the stored PIN instead")
                self._refresh_token = None
        await self._token_request(
            {"grant_type": "password", "username": self._username, "password": self._pin}
        )

    async def _headers(self) -> dict[str, str]:
        if not self._access_token or time.monotonic() >= self._access_expires:
            await self.async_login()
        return {
            "authorization": f"Bearer {self._access_token}",
            "accept": "application/json, text/plain, */*",
            "api-version": "1",
            "iii-customer-domain": self._domain,
            "iii-host-domain": self._host_domain,
        }

    async def async_get_holds(self) -> list[Hold]:
        """Return all holds, retrying once if the token was rejected."""
        for attempt in (1, 2):
            headers = await self._headers()
            try:
                async with self._session.get(
                    self._holds_url,
                    params={"placedHoldIds": ""},
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        self._access_token = None
                        continue
                    if resp.status in (401, 403):
                        raise VegaAuthError(f"Holds endpoint returned {resp.status}")
                    resp.raise_for_status()
                    data = await resp.json()
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise VegaConnectionError(f"holds request failed: {err!r}") from err
            if not isinstance(data, list):
                raise VegaConnectionError(f"holds response was {type(data).__name__}, expected a list")
            holds = self._parse_holds(data)
            _LOGGER.debug("Fetched %d holds", len(holds))
            return holds
        raise VegaConnectionError("Could not fetch holds")  # pragma: no cover

    def _parse_holds(self, items: list[Any]) -> list[Hold]:
        holds: list[Hold] = []
        for item in items:
            try:
                hold = parse_hold(item)
            except (AttributeError, KeyError, TypeError, ValueError) as err:
                keys = sorted(item) if isinstance(item, dict) else type(item).__name__
                _LOGGER.warning("Skipping a hold that could not be parsed (%r): %s", keys, err)
                continue
            if (
                hold.status not in KNOWN_STATUS_CODES
                and hold.priority != 0
                and hold.status not in self._warned_codes
            ):
                self._warned_codes.add(hold.status)
                _LOGGER.warning(
                    "Unrecognised hold status code %r (queue position %s, vendor %s); "
                    "treating it as '%s'. Please report it at %s",
                    hold.status,
                    hold.priority,
                    hold.vendor,
                    hold.status_name,
                    ISSUES_URL,
                )
            holds.append(hold)
        return holds

    async def async_fetch_cover(self, url: str) -> bytes | None:
        """Download a cover image; None if unavailable."""
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                return await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug("Cover download failed for %s: %r", url, err)
            return None

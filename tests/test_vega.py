"""Tests for the pure-Python parts (no Home Assistant needed).

Run with:  pip install pytest pytest-asyncio aiohttp pillow && pytest
"""

import importlib.util
import io
import pathlib
import sys
import types

import pytest
from PIL import Image

PKG = pathlib.Path(__file__).parent.parent / "custom_components" / "vega_library"


def _load(name: str):
    """Import api.py / montage.py directly so the HA-dependent __init__ is not executed."""
    spec = importlib.util.spec_from_file_location(f"vega_{name}", PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


api = _load("api")
montage = _load("montage")


def _png(width=60, height=90, color=(200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, "PNG")
    return out.getvalue()


# ---------- parsing ----------

RAW_READY = {
    "id": "1",
    "priority": 0,
    "status": "b",
    "frozen": False,
    "vendor": "gates",
    "priorityQueueLength": 0,
    "expirationDate": "2026-11-15T05:59:59Z",
    "resource": {
        "title": "Poached",
        "primaryAgent": {"label": "Gibbs, Stuart, 1969-"},
        "coverUrl": {"small": "s", "medium": "m", "large": "l"},
    },
}


def test_parse_ready_hold():
    hold = api.parse_hold(RAW_READY)
    assert hold.ready
    assert hold.title == "Poached"
    assert hold.cover_url == "m"
    assert hold.expires.isoformat() == "2026-11-15T05:59:59+00:00"


def test_parse_waiting_hold_with_missing_fields():
    hold = api.parse_hold({"id": 2, "priority": 3, "resource": {"title": "X"}})
    assert not hold.ready
    assert hold.cover_url is None
    assert hold.expires is None
    assert hold.author is None


# ---------- montage ----------


def _size(png: bytes):
    return Image.open(io.BytesIO(png)).size


def test_montage_width_is_constant_for_any_count():
    imgs = [_png() for _ in range(8)]
    one = _size(montage.build_montage(imgs[:1], 110, 6, 4, 8))
    four = _size(montage.build_montage(imgs[:4], 110, 6, 4, 8))
    assert one[0] == four[0]


def test_montage_wraps_into_rows():
    imgs = [_png() for _ in range(8)]
    _, h = _size(montage.build_montage(imgs, 110, 6, 4, 8))
    assert h == 2 * 110 + 6


def test_montage_caps_with_more_tile():
    imgs = [_png() for _ in range(12)]
    _, h = _size(montage.build_montage(imgs, 110, 6, 4, 8))
    assert h == 2 * 110 + 6  # still two rows, the last slot is the +N tile


def test_montage_skips_placeholder_and_bad_images():
    tiny = _png(1, 1)
    out = montage.build_montage([tiny, b"not an image", None], 110, 6, 4, 8)
    assert _size(out)[1] == 55  # "no holds" placeholder is half height


# ---------- client ----------


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise api.aiohttp.ClientResponseError(None, (), status=self.status)

    async def json(self):
        return self._payload


class FakeSession:
    def __init__(self, posts, gets):
        self.posts = list(posts)
        self.gets = list(gets)
        self.post_forms = []

    def post(self, url, data=None, **kw):
        self.post_forms.append(data)
        return self.posts.pop(0)

    def get(self, url, **kw):
        return self.gets.pop(0)


def _client(session, **kw):
    return api.VegaClient(session, "lib", "na2.iiivega.com", "card", "pin", **kw)


@pytest.mark.asyncio
async def test_refresh_token_used_before_pin():
    tok = {"access_token": "a", "refresh_token": "r2", "expires_in": 600}
    session = FakeSession([FakeResponse(200, tok)], [FakeResponse(200, [RAW_READY])])
    saved = []
    client = _client(session, refresh_token="r1", token_callback=saved.append)
    holds = await client.async_get_holds()
    assert len(holds) == 1
    assert session.post_forms[0]["grant_type"] == "refresh_token"
    assert saved == ["r2"]


@pytest.mark.asyncio
async def test_falls_back_to_pin_when_refresh_rejected():
    ok = {"access_token": "a", "refresh_token": "r3", "expires_in": 600}
    session = FakeSession(
        [FakeResponse(400), FakeResponse(200, ok)], [FakeResponse(200, [])]
    )
    client = _client(session, refresh_token="stale")
    assert await client.async_get_holds() == []
    assert [f["grant_type"] for f in session.post_forms] == ["refresh_token", "password"]


@pytest.mark.asyncio
async def test_bad_pin_raises_auth_error():
    session = FakeSession([FakeResponse(401)], [])
    with pytest.raises(api.VegaAuthError):
        await _client(session).async_get_holds()


@pytest.mark.asyncio
async def test_unknown_library():
    session = FakeSession([FakeResponse(404)], [])
    with pytest.raises(api.VegaUnknownLibraryError):
        await _client(session).async_get_holds()


@pytest.mark.asyncio
async def test_expired_access_token_is_retried_once():
    ok = {"access_token": "a", "expires_in": 600}
    session = FakeSession(
        [FakeResponse(200, ok), FakeResponse(200, ok)],
        [FakeResponse(401), FakeResponse(200, [RAW_READY])],
    )
    assert len(await _client(session).async_get_holds()) == 1
    assert len(session.post_forms) == 2

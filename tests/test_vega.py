"""Tests for the pure-Python parts (no Home Assistant needed).

Run with:  pip install pytest pytest-asyncio aiohttp pillow && pytest
"""

import importlib
import io
import pathlib
import sys
import types

import pytest
from PIL import Image

PKG = pathlib.Path(__file__).parent.parent / "custom_components" / "vega_library"


def _load(name: str):
    """Import a submodule without executing the HA-dependent package __init__."""
    if "vega_library" not in sys.modules:
        pkg = types.ModuleType("vega_library")
        pkg.__path__ = [str(PKG)]
        sys.modules["vega_library"] = pkg
    return importlib.import_module(f"vega_library.{name}")


api = _load("api")
montage = _load("montage")
events = _load("events")
const = _load("const")
summary = _load("summary")


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

    async def text(self):
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


CONFIG_JS = """var API_URL = 'https://na2.iiivega.com';
var KEYCLOAK_URL = 'https://auth.na2.iiivega.com:443/auth';
"""


@pytest.mark.asyncio
async def test_discover_from_catalog_address():
    session = FakeSession([], [FakeResponse(200, "slouc\n"), FakeResponse(200, CONFIG_JS)])
    found = await api.async_discover(session, "slouc.na2.iiivega.com/search?x=1")
    assert found.site_code == "slouc"
    assert found.host == "na2.iiivega.com"
    assert found.auth_url == "https://auth.na2.iiivega.com/auth"
    assert found.site_host == "slouc.na2.iiivega.com"


@pytest.mark.asyncio
async def test_discover_vanity_domain_keeps_site_host():
    session = FakeSession([], [FakeResponse(200, "mylib"), FakeResponse(200, CONFIG_JS)])
    found = await api.async_discover(session, "https://catalog.mylibrary.org")
    assert (found.site_code, found.site_host) == ("mylib", "catalog.mylibrary.org")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lookup",
    [FakeResponse(404, ""), FakeResponse(200, "<html>not vega</html>")],
)
async def test_discover_rejects_non_vega_sites(lookup):
    session = FakeSession([], [lookup, FakeResponse(200, CONFIG_JS)])
    with pytest.raises(api.VegaUnknownLibraryError):
        await api.async_discover(session, "https://example.com")


@pytest.mark.asyncio
async def test_discover_requires_https():
    with pytest.raises(api.VegaUnknownLibraryError):
        await api.async_discover(FakeSession([], []), "http://example.com")


def test_realm_drops_prefix_before_last_hyphen():
    client = api.VegaClient(None, "grp-mylib", "na2.iiivega.com", "c", "p")
    assert "/realms/mylib/" in client._token_url
    assert client._domain == "grp-mylib.na2.iiivega.com"


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


# ---------- status model ----------

def _hold(id="1", status="0", priority=3, frozen=False, expires=None, **kw):
    return api.Hold(
        id=id, title=f"Book {id}", author=None, vendor="gates", status=status,
        priority=priority, queue_length=5, frozen=frozen, expires=expires,
        cover_url=None, **kw,
    )


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(status="b", priority=0), "ready"),
        (dict(status="0", priority=0), "ready"),  # digital holds: position 0 means ready
        (dict(status="t", priority=1), "in_transit"),
        (dict(status="0", priority=4), "waiting"),
        (dict(status="zzz", priority=2), "waiting"),  # unknown code falls back to waiting
        (dict(status="b", priority=0, frozen=True), "frozen"),
    ],
)
def test_status_name(kwargs, expected):
    assert _hold(**kwargs).status_name == expected


def test_as_dict_has_cover_urls_and_status():
    d = api.parse_hold(RAW_READY).as_dict()
    assert d["status"] == "ready"
    assert d["cover_url"] == "m" and d["cover_url_large"] == "l"
    assert d["pickup_by"] == "2026-11-15T05:59:59+00:00"


# ---------- events ----------

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def _types(evts):
    return [(t, h.id) for t, h, _ in evts]


def test_first_poll_fires_nothing_but_records_deadlines():
    soon = _hold("1", "b", 0, expires=NOW + timedelta(days=1))
    notified = set()
    assert events.diff_holds(None, [soon], NOW, 2, notified) == []
    assert notified  # remembered, so it does not fire after the next poll
    assert events.diff_holds([soon], [soon], NOW, 2, notified) == []


def test_waiting_to_ready_fires_status_changed_and_ready():
    before = [_hold("1", "0", 1)]
    after = [_hold("1", "b", 0)]
    out = events.diff_holds(before, after, NOW, 0, set())
    assert _types(out) == [
        (const.EVENT_HOLD_STATUS_CHANGED, "1"),
        (const.EVENT_HOLD_READY, "1"),
    ]
    assert out[1][2]["previous_status"] == "waiting"


def test_new_and_removed_holds():
    out = events.diff_holds([_hold("1")], [_hold("2", "b", 0)], NOW, 0, set())
    assert _types(out) == [
        (const.EVENT_HOLD_ADDED, "2"),
        (const.EVENT_HOLD_READY, "2"),
        (const.EVENT_HOLD_REMOVED, "1"),
    ]


def test_deadline_warning_fires_once_and_not_for_expired():
    ready = _hold("1", "b", 0, expires=NOW + timedelta(days=1))
    expired = _hold("2", "b", 0, expires=NOW - timedelta(hours=1))
    far = _hold("3", "b", 0, expires=NOW + timedelta(days=9))
    notified = set()
    first = events.diff_holds([ready, expired, far], [ready, expired, far], NOW, 2, notified)
    assert _types(first) == [(const.EVENT_PICKUP_DEADLINE, "1")]
    assert first[0][2]["days_left"] == 1.0
    assert events.diff_holds([ready], [ready], NOW, 2, notified) == []


def test_deadline_disabled_with_zero_days():
    ready = _hold("1", "b", 0, expires=NOW + timedelta(hours=5))
    assert events.diff_holds([ready], [ready], NOW, 0, set()) == []


# ---------- diagnostics summary / logging ----------


def test_summary_has_no_titles_authors_or_ids():
    holds = [_hold("secret-id-1", "b", 0), _hold("secret-id-2", "t", 1)]
    out = summary.summarize_holds(holds)
    text = repr(out)
    assert "Book" not in text and "secret-id" not in text
    assert out["by_status"] == {"ready": 1, "in_transit": 1}
    assert {c["code"] for c in out["raw_status_codes"]} == {"b", "t"}


def test_unknown_status_code_warns_once(caplog):
    client = api.VegaClient(None, "lib", "na2.iiivega.com", "c", "p")
    item = {"id": 1, "priority": 3, "status": "zz", "resource": {"title": "X"}}
    with caplog.at_level("WARNING"):
        client._parse_holds([item, item])
    assert len([r for r in caplog.records if "Unrecognised hold status code" in r.message]) == 1


def test_unparseable_hold_is_skipped_with_a_warning(caplog):
    client = api.VegaClient(None, "lib", "na2.iiivega.com", "c", "p")
    bad = {"id": 1, "priority": None, "resource": {}}
    with caplog.at_level("WARNING"):
        assert client._parse_holds([bad, RAW_READY]) != []
    assert any("could not be parsed" in r.message for r in caplog.records)


def test_pin_is_never_logged(caplog):
    session = FakeSession([FakeResponse(401)], [])
    client = api.VegaClient(session, "lib", "na2.iiivega.com", "1234567890", "9999")
    with caplog.at_level("DEBUG"), pytest.raises(api.VegaAuthError):
        import asyncio
        asyncio.run(client.async_get_holds())
    assert "9999" not in caplog.text and "1234567890" not in caplog.text

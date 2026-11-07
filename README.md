# Vega Library Holds for Home Assistant

Shows your library holds from a **Vega Discover** (Innovative / III) catalog in Home Assistant, including one picture of the covers of everything that is ready for pickup, handy for a wall dashboard.

> Unofficial. It talks to the same patron endpoints your library's own website uses and is not affiliated with Innovative or your library. Those endpoints can change without notice.

## What you get

| Entity | Description |
|---|---|
| `sensor` Total holds | Number of holds on your account |
| `sensor` Ready for pickup | Number ready now. Attributes: `titles`, and `holds` (title, author, pickup-by date) |
| `sensor` Next pickup deadline | Earliest pickup-by date among ready holds (timestamp) |
| `image` Ready for pickup covers | PNG of the ready books' covers in a grid. Always the same width, so covers keep the same size on a dashboard whether 1 or 8 are ready; extras beyond the limit become a "+N" tile |

## Install

**HACS (custom repository):** HACS → ⋮ → Custom repositories → add this repo as type *Integration* → download → restart Home Assistant.

**Manual:** copy `custom_components/vega_library` into your Home Assistant `custom_components` folder and restart.

Then: Settings → Devices & services → Add integration → *Vega Library Holds*.

## Setup

You need:

- **Library ID**: the first part of your library's Vega address, e.g. `mylibrary` for `mylibrary.na2.iiivega.com`.
- **Vega host**: `na2.iiivega.com` for North American libraries (the default).
- **Card number and PIN**: what you use to sign in on the library's site.

> Tested against one library only. Libraries on a custom domain, or other regions, may need different values. Please open an issue with what you find (leave out your card number and PIN).

## Authentication

Your card number and PIN are stored in the integration's config entry (Home Assistant's `.storage`, **not encrypted**), the same trust level as a password in `secrets.yaml`. The integration signs in once, then uses the refresh token the library returns (valid about 90 days and renewed each time it is used). If a refresh is ever rejected it signs in again with the stored PIN, so you are not prompted on a schedule. You only get a *Re-authenticate* prompt if the library rejects the PIN itself, for example after you change it.

## Options

Settings → Devices & services → Vega Library Holds → Configure: check interval (default 2 hours), covers per row, the most covers to show, and cover height.

## Dashboard example

```yaml
type: picture-entity
entity: image.library_mylibrary_1234_ready_for_pickup_covers
show_name: false
show_state: false
```

Use `visibility` on the card to hide it when `sensor.…_ready_for_pickup` is 0.

## Development

```
pip install pytest pytest-asyncio aiohttp pillow
pytest
```

The tests cover parsing, token refresh and fallback, and the image layout without needing Home Assistant.

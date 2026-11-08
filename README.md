# Vega Library Holds for Home Assistant

Shows your library holds from a **Vega Discover** (Innovative / III) catalog in Home Assistant, including one picture of the covers of everything that is ready for pickup, handy for a wall dashboard.

> Unofficial. It talks to the same patron endpoints your library's own website uses and is not affiliated with Innovative or your library. Those endpoints can change without notice.

## What you get

Every hold has a **status**: `ready` (waiting for pickup), `in_transit`, `waiting` (in the queue) or `frozen`.

| Entity | Description |
|---|---|
| `sensor` All holds | Number of holds of every status. The `holds` attribute lists every hold (see below) |
| `sensor` Ready for pickup | Count of ready holds. Attributes: `titles`, and `holds` for just the ready ones |
| `sensor` In transit | Count of holds moving between branches, with `holds` |
| `sensor` Waiting in queue | Count of holds still in the queue, with `holds` |
| `sensor` Next pickup deadline | Earliest pickup-by date among ready holds (timestamp) |
| `image` Ready for pickup covers | One PNG of the ready books' covers in a grid. Always the same width, so covers keep the same on-screen size whether 1 or 8 are ready; extras beyond the limit become a "+N" tile |

Each entry in a `holds` list contains: `id`, `title`, `author`, `status`, `position` (place in the queue, 0 = ready), `queue_length`, `vendor` (the library's source for the item, e.g. a physical collection or a digital provider), `frozen`, `pickup_by`, `cover_url` and `cover_url_large`. The `holds` and `titles` attributes are excluded from the recorder so they do not fill the history database.

> Status is derived from the library's status code and queue position. Only a few codes have been seen (ready, in transit, waiting); anything unrecognised is reported as `waiting`.

### Covers in your own cards

`cover_url` points at the library's cover-image provider. Your browser loads it directly, as it does on the library's own site. A cover that does not exist comes back as a 1×1 blank image; the combined image entity skips those, a custom card using the raw URL will show a blank.

### Events

The integration compares each check with the previous one and fires events on the Home Assistant event bus. Nothing fires on the first check after setup or a restart, so books that were already waiting do not trigger a flood of alerts.

| Event | When | Extra data |
|---|---|---|
| `vega_library_hold_ready` | A hold became ready for pickup | `previous_status` |
| `vega_library_hold_status_changed` | Any status change | `previous_status` |
| `vega_library_hold_added` | A new hold appeared | |
| `vega_library_hold_removed` | A hold disappeared (picked up, cancelled or expired; the library does not say which) | |
| `vega_library_pickup_deadline` | A ready hold is within the warning window (default 2 days, 0 turns it off), once per hold | `days_left` |

Every event carries `entry_id`, `library`, and `hold` (the dictionary above).

```yaml
automation:
  - alias: Library hold ready
    triggers:
      - trigger: event
        event_type: vega_library_hold_ready
    actions:
      - action: notify.notify
        data:
          message: >-
            {{ trigger.event.data.hold.title }} is ready for pickup
            {% if trigger.event.data.hold.pickup_by %}
            until {{ as_timestamp(trigger.event.data.hold.pickup_by) | timestamp_custom('%b %-d') }}
            {% endif %}
```

## Install

**HACS (custom repository):** HACS → ⋮ → Custom repositories → add this repo as type *Integration* → download → restart Home Assistant.

**Manual:** copy `custom_components/vega_library` into your Home Assistant `custom_components` folder and restart.

Then: Settings → Devices & services → Add integration → *Vega Library Holds*.

## Setup

You need:

- **Library catalog address**: the web address of your library's online catalog, the Vega page where you search for books and sign in (for example `https://mylibrary.na2.iiivega.com`). This must be the Vega catalog itself, not the library's main website.
- **Card number and PIN**: what you use to sign in on the catalog.

The library ID, Vega region and sign-in server are detected automatically from the address: every Vega site serves its site code at `/lookup` and its API and sign-in URLs at `/config.js`, which is what the Vega web app reads on startup.

> Tested against one library only (on the standard `*.iiivega.com` address). A library using its own domain name should work the same way, since the Vega site answers on that domain too, but that is untested. Please open an issue with what you find (leave out your card number and PIN).

## Authentication

Your card number and PIN are stored in the integration's config entry (Home Assistant's `.storage`, **not encrypted**), the same trust level as a password in `secrets.yaml`. The integration signs in once, then uses the refresh token the library returns (valid about 90 days and renewed each time it is used). If a refresh is ever rejected it signs in again with the stored PIN, so you are not prompted on a schedule. You only get a *Re-authenticate* prompt if the library rejects the PIN itself, for example after you change it.

## Options

Settings → Devices & services → Vega Library Holds → Configure: check interval (default 2 hours), covers per row, the most covers to show, cover height, and how many days before a pickup deadline to warn.

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

The tests cover parsing, the status model, event detection, address discovery, token refresh and fallback, and the image layout, without needing Home Assistant.

## License

MIT. See [LICENSE](LICENSE).

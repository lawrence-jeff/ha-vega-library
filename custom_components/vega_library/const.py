"""Constants for the Vega Library Holds integration."""

DOMAIN = "vega_library"

CONF_LIBRARY_ID = "library_id"
CONF_HOST = "host"
CONF_AUTH_URL = "auth_url"
CONF_SITE_HOST = "site_host"
CONF_SITE_URL = "site_url"  # only used in the setup form


# Options
CONF_SCAN_INTERVAL = "scan_interval"  # minutes
CONF_COLUMNS = "columns"
CONF_MAX_COVERS = "max_covers"
CONF_COVER_HEIGHT = "cover_height"
CONF_DEADLINE_DAYS = "deadline_days"  # warn this many days before a pickup deadline; 0 = off

DEFAULT_SCAN_INTERVAL = 120
DEFAULT_COLUMNS = 4
DEFAULT_MAX_COVERS = 8
DEFAULT_COVER_HEIGHT = 110
DEFAULT_DEADLINE_DAYS = 2

COVER_GAP = 6

STORAGE_VERSION = 1

# Hold statuses (derived from the library's status code and queue position)
STATUS_READY = "ready"
STATUS_IN_TRANSIT = "in_transit"
STATUS_WAITING = "waiting"
STATUS_FROZEN = "frozen"

# Bus events
EVENT_HOLD_READY = f"{DOMAIN}_hold_ready"
EVENT_HOLD_STATUS_CHANGED = f"{DOMAIN}_hold_status_changed"
EVENT_HOLD_ADDED = f"{DOMAIN}_hold_added"
EVENT_HOLD_REMOVED = f"{DOMAIN}_hold_removed"
EVENT_PICKUP_DEADLINE = f"{DOMAIN}_pickup_deadline"

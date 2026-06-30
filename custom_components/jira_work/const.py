"""Constants for the Jira Work integration."""

DOMAIN = "jira_work"

# Storage
STORAGE_KEY = "jira_work"
STORAGE_VERSION = 1

# Config entry keys
CONF_URL = "url"
CONF_EMAIL = "email"
CONF_TOKEN = "token"
CONF_TOKEN_TYPE = "token_type"
CONF_CLOUD_ID = "cloud_id"

# Token types
TOKEN_TYPE_CLASSIC = "classic"
TOKEN_TYPE_SCOPED = "scoped"

# Scoped token gateway — base URL is https://api.atlassian.com/ex/jira/{cloudId}
SCOPED_API_BASE = "https://api.atlassian.com/ex/jira"
TENANT_INFO_PATH = "/_edge/tenant_info"

# JQL
JQL_OPEN_ASSIGNED = (
    "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
)

# Core fields always requested in JQL searches
CORE_FIELDS = ["summary", "status", "priority", "issuetype", "project", "duedate", "assignee"]

# Polling / checkpointing
DEFAULT_POLL_INTERVAL = 5          # minutes
CHECKPOINT_EVERY = 12              # polls (12 × 5 min = hourly)
DEFAULT_CHECKPOINT_EVERY = 12

# Rolling window
ROLLING_WINDOW_HOURS = 24          # hours — default for new_last_window sensor

# Options keys
OPT_POLL_INTERVAL = "poll_interval"
OPT_DUE_WITHIN_DAYS = "due_within_days"
OPT_CUSTOM_FIELDS = "custom_fields"
OPT_CHECKPOINT_EVERY = "checkpoint_every"
OPT_HIGH_PRIORITY_NAMES = "high_priority_names"    # list[str] of priority names
OPT_ROLLING_WINDOW_HOURS = "rolling_window_hours"  # int, hours for new_last_window sensor

# Defaults
DEFAULT_HIGH_PRIORITY_NAMES = ["Blocker", "Critical"]
DEFAULT_DUE_WITHIN_DAYS = 3

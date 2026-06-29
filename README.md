# Jira Work — Home Assistant Integration

A Home Assistant custom integration that surfaces your open, assigned Jira Cloud work items as sensors — making them available for dashboards and automations.

## Features

- **Total open assigned** — count of all open issues assigned to you
- **Overdue** — issues past their due date, with keys as attributes
- **Due soon** — issues due within a configurable window (default 3 days)
- **High priority** — issues matching your configured priority levels (default: Blocker, Critical)
- **Newly assigned** — issues assigned to you since the last poll (transient)
- **New in rolling window** — issues assigned within a configurable rolling window (default 24 hours)

All sensors expose breakdowns by project, type, status, and priority as attributes. Custom Jira fields (e.g. Story Points) can be tracked and summed.

## Installation

### HACS (recommended)

1. Add this repository to HACS as a custom repository
2. Install **Jira Work** from HACS
3. Restart Home Assistant

### Manual

Copy `custom_components/jira_work/` to your HA `custom_components/` directory and restart.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Jira Work**
3. Enter your Jira Cloud URL, account email, and [API token](https://id.atlassian.com/manage-profile/security/api-tokens)

## Options

After setup, configure via **Settings → Devices & Services → Jira Work → Configure**:

| Option | Default | Description |
|--------|---------|-------------|
| Custom fields to track | (none) | Jira custom fields to include as attributes |
| High-priority levels | Blocker, Critical | Priority names that count as high-priority |
| Poll interval | 5 min | How often to query Jira |
| Due-soon window | 3 days | Window for the "due soon" sensor |
| Rolling window | 24 hours | Window for the "new in window" sensor |

## Requirements

- Home Assistant 2026.2.3 or later
- Jira Cloud account with API token

## Links

- [Documentation](https://github.com/brownkw/ha-jira-integration)
- [Issues](https://github.com/brownkw/ha-jira-integration/issues)

## License

MIT

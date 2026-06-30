# Jira Work — Home Assistant Integration

I built this because I wanted my Jira workload visible on my Home Assistant dashboard without having to open a browser. It pulls your open, assigned Jira Cloud issues and turns them into sensors you can use in dashboards, automations, and alerts.

## What it tracks

- **Total open** — all open issues assigned to you
- **Overdue** — issues past their due date (issue keys available as attributes)
- **Due soon** — issues due within a configurable window (default: 3 days)
- **High priority** — issues matching priority levels you define (default: Blocker, Critical)
- **Newly assigned** — issues assigned to you since the last poll
- **New in rolling window** — issues assigned within a configurable window (default: 24 hours)

Every sensor includes breakdowns by project, type, status, and priority as attributes. You can also track and sum custom Jira fields like Story Points.

## Installation

### HACS (recommended)

1. Add this repository to HACS as a custom integration
2. Install **Jira Work**
3. Restart Home Assistant

### Manual

Copy `custom_components/jira_work/` into your HA `custom_components/` directory and restart.

## Setup

Go to **Settings → Devices & Services → Add Integration** and search for **Jira Work**.

You'll need:
- Your Jira Cloud URL (e.g. `https://yoursite.atlassian.net`)
- Your account email
- An [API token](https://id.atlassian.com/manage-profile/security/api-tokens)

**Scoped token users:** select *Scoped* as the token type and enter your Cloud ID. You can find your Cloud ID at `https://yoursite.atlassian.net/_edge/tenant_info`. Required scopes: `read:jira-work` + `read:jira-user`.

> **Note on setup time:** the first-time config flow fetches your assigned issues and filters the custom field list down to fields that actually appear on your work. On large Jira instances this can take 15–30 seconds. It only happens once.

## Options

After setup, go to **Settings → Devices & Services → Jira Work → Configure**:

| Option | Default | Description |
|--------|---------|-------------|
| Custom fields to track | (none) | Fields to include as sensor attributes |
| High-priority levels | Blocker, Critical | Priority names that count toward the high-priority sensor |
| Poll interval | 5 min | How often to query Jira |
| Due-soon window | 3 days | Lookforward window for the due-soon sensor |
| Rolling window | 24 hours | Lookback window for the new-in-window sensor |

## Requirements

- Home Assistant 2026.2.3 or later
- Jira Cloud account

## License

MIT

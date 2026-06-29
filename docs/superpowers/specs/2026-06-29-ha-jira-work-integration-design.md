# Home Assistant Jira Work Integration — Design

**Date:** 2026-06-29
**Status:** Approved (design phase complete; ready for implementation planning)

## Summary

A custom Home Assistant integration that surfaces your open, assigned Jira work
as sensors, aggregated across multiple pivot points (project, work item type,
status, priority) and exposing a small set of "alertable" derived sensors
(overdue, due-within-X, high priority, newly assigned). Target is **Jira Cloud**,
authenticated with an **API token** (HTTP Basic: `email:token`).

This is net-new in the Home Assistant ecosystem: there is no native HA Jira
integration today (only middleware glue via tools like n8n / Pipedream).

## Goals

- Show count of open assigned work items as a primary sensor.
- Aggregate by pivots: project, work item type, status, priority.
- Provide alertable sensors for time/priority pressure.
- Track an arbitrary, **user-changeable** set of Jira custom fields.
- Run comfortably on a low-powered host (resource use is negligible at this scale).

## Non-Goals (YAGNI)

- No OAuth (API token is sufficient for a personal, non-shared instance; OAuth
  can be added later as a second auth method without reworking the core).
- No dynamic entity-per-bucket (avoids entity explosion). Pivots live in
  attributes; individual buckets are promoted to dedicated sensors only by a
  deliberate code change.
- No "fetch all custom fields" firehose; tracked fields are explicitly selected.
- No OAuth and no submission to the HACS **default** store (Tier 2) yet. The
  repo is, however, structured to be **HACS-installable via a GitHub URL**
  (Tier 1 "custom repository") from day one — see Packaging / Distribution.

## Approach Decision

Evaluated **(B)** a full custom integration vs **(C)** a `command_line` sensor +
script. Chose **B**. The deciding factors:

- **Changeable custom fields** want an Options Flow (UI to add/remove tracked
  fields with friendly names, no restart) — clean in B, fiddly in C.
- **"Newly assigned"** wants a stateful coordinator that remembers prior polls —
  natural in B, awkward in C (stateless script).

The Jira-specific logic (`api.py` + `aggregator.py`) is kept **HA-free**, so it
is independently reusable (CLI, cron, other platforms) and easily unit-tested.

## Architecture & Components

Package: `custom_components/jira_work/`

Dependency direction (one-way):

```
sensor.py ─┐
           ├─> coordinator.py ─> api.py (JiraClient)
config_flow ┘                └─> aggregator.py
                                   (api + aggregator have ZERO HA imports)
```

- **`api.py` — `JiraClient`** (no HA dependency)
  Auth (Basic `email:token`), JQL `search` with pagination, `/field` lookup for
  custom-field ID → friendly name. Pure async HTTP. Reusable core.

- **`aggregator.py` — pure functions** (no HA dependency)
  Input: raw issue list + config (tracked custom fields, due-within horizon).
  Output: total, pivot dicts, alertable counts, normalized custom-field values.
  Stateless; trivially unit-testable.

- **`coordinator.py` — `JiraDataUpdateCoordinator`** (HA)
  Subclass of `DataUpdateCoordinator`. Each interval: fetch via client → shape
  via aggregator → store result. Holds the **prior issue-key set** and the
  **recent-key list (with timestamps)** for the newly-assigned sensors (the
  stateful logic that can't live in the pure aggregator).

- **`config_flow.py` — `ConfigFlow` + `OptionsFlow`** (HA)
  ConfigFlow: initial setup (Jira URL, email, API token), validated by a test
  call. OptionsFlow: live editor for tracked custom fields, poll interval,
  due-within horizon, (optional) checkpoint interval.

- **`sensor.py` — sensor entities** (HA)
  The Shape 1+ entities (below). Read-only from the coordinator; no I/O.

- **`__init__.py` + `manifest.json`** (HA)
  Standard entry setup, client + coordinator instantiation, platform forwarding;
  manifest with `config_flow: true` and dependencies.

## Data Flow & Polling

Poll cycle (default 5 min, configurable):

1. Coordinator timer fires → `JiraClient.search()`.
2. One JQL query:
   `assignee = currentUser() AND statusCategory != Done ORDER BY duedate ASC`,
   requesting an **explicit field list** (core fields + configured custom field
   IDs) to keep payloads small.
3. Client paginates (`startAt`/`maxResults`) until all issues gathered.
4. Client returns the raw issue list (no shaping).
5. Coordinator runs issues + config through `aggregator`. Date-relative math
   (overdue, due-within-X) uses local "now" at compute time.
6. Coordinator computes newly-assigned via key set-diff (see below).
7. Coordinator stores shaped result; HA notifies sensors, which read their slice.

Field-name resolution: `/field` (ID → friendly name) is fetched at setup and when
the Options Flow opens, then cached — **not** on every poll. The poll works with
IDs only.

Config-change flow: saving Options triggers a config-entry **reload** (update
listener). Coordinator rebuilds with the new field list; next poll picks it up.
No HA restart.

### "Newly assigned" determination

Set difference between consecutive polls, held in the coordinator:

- `current` = set of open-assigned issue keys this poll.
- `newly_assigned = current - previous`; then `previous = current`.
- **First poll** treats `previous = current` → reports 0 (no startup flood).

Two sensors, complementary:

- **Transient spike** (`sensor.jira_newly_assigned`): resets to 0 on the next
  poll. Ideal for automations ("new item → notify me now").
- **Rolling window** (`sensor.jira_new_last_24h`): keeps a list of
  `(key, first_seen_ts)`, prunes entries older than the window; count = entries
  within window. Better for at-a-glance dashboards.

Rationale for key set-diff over JQL changelog: self-contained, no dependence on
Jira changelog/JQL functions; the only state needed lives in the coordinator.

### Persistence (Option 2: shutdown + load + hourly checkpoint)

- Uses HA's async `Store` helper (JSON). Shared `_serialize()` / `_deserialize()`
  handle the key-set + recent-list (with timestamps; prune expired on load).
- **Load on startup** before first poll.
- **Write on `homeassistant_stop`** (graceful shutdown).
- **Hourly checkpoint** (`poll_count % CHECKPOINT_EVERY == 0`) so a hard crash
  loses at most ~1 hour, not everything since last graceful shutdown.
- Corrupt/missing store on load → start fresh; never block startup.

Resource note: writes are a few KB; CPU per poll is trivial (one HTTPS call +
iterating tens of issues). The only real budget to respect is **Jira Cloud rate
limits**, handled by the single-query, 5-min-interval design.

## Sensors, Attributes & Options Flow

### Sensor set (Shape 1+, 6 entities)

**Primary — `sensor.jira_open_assigned`**
- State: total open assigned count.
- Attributes:
  - `by_project: {…}`, `by_type: {…}`, `by_status: {…}`, `by_priority: {…}`
  - `custom_fields: {…}` (normalized; numeric fields may be summed,
    e.g. `story_points_total`)
  - `last_updated`

**Alertable (state = count; `keys` attribute lists the issue keys behind it):**
- `sensor.jira_overdue` — overdue count.
- `sensor.jira_due_within_x` — due within configured horizon; attr `horizon_days`.
- `sensor.jira_high_priority` — High/Highest open count.
- `sensor.jira_newly_assigned` — transient spike; attr `new_keys`.
- `sensor.jira_new_last_24h` — rolling count; attr `window_hours`.

Entity metadata: all grouped under one HA **device**; `state_class: measurement`
on counts (free history/graphs); per-sensor icons; stable unique IDs.

### Options Flow (changeable custom fields)

Form fields:
1. **Tracked custom fields** — multi-select populated from `/field`, showing
   **friendly names**, storing underlying IDs. Editable anytime.
2. **Poll interval** (default 5 min).
3. **Due-within-X-days horizon** (default 3).
4. **Checkpoint interval** (optional to expose).

Scope boundary: the Options Flow controls **which custom fields appear in the
`custom_fields` attribute** (and optionally which categorical ones become extra
pivots). It does **not** create new top-level sensors per field (avoids entity
explosion). Promoting a field/type to a dedicated sensor is a deliberate code
change.

### Custom-field handling

- **Normalize** values to display-friendly forms (extract `.value`/`.name`, join
  arrays, etc.); fall back to `str(value)` for unrecognized shapes.
- **Sum numeric** custom fields across open items where useful.
- **Duplicate friendly names**: keyed internally by immutable `customfield_xxxxx`
  ID (never ambiguous for data). When `/field` returns colliding display names,
  **disambiguate in the dropdown** by appending the ID, e.g.
  `Team (customfield_10031)` vs `Team (customfield_10044)`.

### Custom work item types

Handled automatically and dynamically. `by_type` buckets on
`issue.fields.issuetype.name`, so custom types (e.g. **Migration**, **Deal**)
appear with no special handling and no hardcoded list. New types added in Jira
later show up on the next poll. They live in the `by_type` attribute (not
dedicated sensors) for now.

## Error Handling

**Setup / config flow (fail loud):**
- 401/403 → "invalid auth"; never store unauthenticated credentials.
- Bad/unreachable URL → "cannot connect".
- Auth-valid-but-no-JQL-permission → caught in the validating test call.

**Poll time (fail soft):**
- Transient (network/5xx/timeout) → raise `UpdateFailed`; sensors go
  `unavailable` for that cycle; auto-retry next interval; state not lost.
- 429 → respect `Retry-After`; back off.
- Post-setup auth break (revoked token) → after repeated 401s, trigger HA
  **reauth flow** (UI prompt) rather than failing silently forever.
- Persistence load failure (corrupt/missing) → start fresh; never block startup.

**Data-shape resilience:**
- Missing/null fields (no due date, no priority, null custom field) handled
  safely (skip math; bucket as "None"/"Unprioritized"); one bad issue never
  breaks the aggregation.
- Configured custom field deleted in Jira → returns nothing; Options stops
  offering it after next `/field` fetch.
- Unexpected custom-field value shape → `str(value)` fallback.

## Testing

The fiddly, risk-heavy logic lives in the **HA-free** layer, which is the easiest
to test exhaustively with plain pytest (no live Jira; mock HTTP; fixture
responses; frozen time for date math).

**Unit (pure, fast):**
- `aggregator`: pivots correct; overdue/due-within math (frozen now); numeric
  custom-field summing; edge cases (null due date, missing priority, unknown
  value shapes, empty list, custom issue types in `by_type`).
- `api`/client: pagination assembly; auth header; JQL field-list building;
  `/field` resolution incl. duplicate-name disambiguation; error mapping
  (401→auth, 429→retry).
- set-diff / newly-assigned: first-poll-0; new-key detection; transient reset;
  rolling-window prune; serialize↔deserialize round-trip (incl. timestamps).

**Integration-ish (HA-aware, lighter):**
- Config flow: happy path; bad auth / bad URL errors; reauth on post-setup 401.
- Options flow: field selection persists IDs; save reloads entry.
- Coordinator: mocked client populates `coordinator.data`; sensors read correct
  values; exception → `UpdateFailed` (unavailable, no crash).

## Packaging / Distribution

Goal: keep the simple **token-based** approach, but structure the repo so it can
be **installed via a GitHub URL** as a HACS custom repository if/when sharing is
desired. This is all additive repo hygiene — no code changes vs. the personal
build.

**Tier 1 — HACS-installable via GitHub URL (target now):**
- Repo layout: integration at `custom_components/jira_work/` at the repo root
  (already the planned layout).
- Complete, valid `manifest.json`: `domain`, `name`, `version`,
  `documentation` URL, `issue_tracker` URL, `codeowners`, `requirements`
  (pinned deps), `iot_class: cloud_polling`, `config_flow: true`.
- `hacs.json` at repo root (HACS metadata: `name`, optional min HA version).
- Real `README.md` (install steps, config, screenshots), `LICENSE` (MIT),
  `.gitignore`.
- Versioned git tags / GitHub releases (HACS installs by tag, e.g. `v0.1.0`).

Result: a user adds the GitHub URL as a HACS "custom repository" and installs.

**Tier 2 — HACS default store (deferred, optional):**
- Submit repo to the HACS `default` list (must pass `hacs/action` validation).
- Add a `home-assistant/brands` entry/logo for the domain.
- UI translations (`strings.json`), `hassfest` validation, broader test
  coverage, and ongoing maintenance across HA releases.
- Public distribution best practice would favor **OAuth** over a long-lived
  token at this point (added as a second auth method; the client/aggregator are
  auth-agnostic).

## Open Items / Future

- OAuth as a second auth method (only if published/shared).
- Promote a specific custom field or work item type to a dedicated alertable
  sensor if a real automation need emerges.
- Optional categorical-custom-field pivots (`by_<field>`).

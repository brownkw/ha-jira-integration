# Decision Log — HA Jira Work Integration

This file captures the **reasoning** behind the design (the "why"), which the spec
and plan intentionally don't re-litigate. It travels with the repo so the project
is self-contained for resuming later.

- **Spec:** `docs/superpowers/specs/2026-06-29-ha-jira-work-integration-design.md`
- **Plan:** `docs/superpowers/plans/2026-06-29-ha-jira-work-integration.md`

---

## Current Status

- ✅ Design complete and approved.
- ✅ Implementation plan complete, self-reviewed, committed.
- ⏳ **Implementation NOT started.**
- **Next action:** execute **Task 1** (scaffolding & test tooling) from the plan.
  Recommended execution mode: subagent-driven-development (fresh subagent per
  task, review between tasks) or executing-plans (inline, batched checkpoints).

---

## Key Decisions & Rationale

### Approach: custom integration (B), not command_line sensor (C)
We compared a full custom integration (B) vs. a `command_line` sensor + script
(C). Chose **B**. The two deciders:
- **Changeable custom fields** want an Options Flow (UI to add/remove tracked
  fields with friendly names, no restart) — clean in B, fiddly YAML + manual
  `customfield_` IDs in C.
- **"Newly assigned"** wants a stateful coordinator that remembers prior polls —
  natural in B, awkward in stateless C.
Shareability was explicitly NOT a deciding factor (see packaging below).
We kept the Jira logic (`api.py` + `aggregator.py`) **HA-free** so the "Jira
brain" is reusable elsewhere and unit-testable without HA — this also means the
work that would have gone into C's core is not throwaway.

### Auth: API token (Basic), not OAuth
Personal, single-user, non-shared instance → a long-lived API token (HTTP Basic
`email:token`) is sufficient and far simpler. OAuth's value (scoping,
revocability) only matters for published/multi-user contexts. OAuth is deferred
to "Tier 2 / if published," and can be added later as a *second* auth method
without reworking the client/aggregator (they are auth-agnostic — they just need
a valid header). Target is **Jira Cloud** only.

### Sensor shape: "Shape 1+", not per-bucket entities
Considered three shapes:
1. Single sensor, pivots in attributes.
2. A few sensors, one per pivot dimension.
3. Dynamic entity-per-bucket (one sensor per project, per type, ...).
**Rejected Shape 3** explicitly to avoid **entity explosion** (a stated user
concern and a real maintenance burden). Landed on **Shape 1+**: one primary
`open_assigned` sensor (total + all pivots in attributes) PLUS a small fixed set
of alertable sensors. Promoting any pivot/bucket to its own sensor is a
deliberate code change, not config.

### Alertable sensors chosen
Filter applied: "would you build an automation on this?" Selected: **overdue,
due-within-X, high-priority** (pure-derived from one query) + **newly-assigned**.
Newly-assigned ships as TWO sensors because they answer different questions:
- **Transient spike** (`newly_assigned`): resets to 0 next poll → ideal for
  "new item → notify me now" automations.
- **Rolling window** (`new_last_window`, 24h): better for at-a-glance dashboards.
Each alertable sensor carries a `keys` attribute (the actual issue keys) so
automations can reference *which* items, not just a count.

### High-priority names: user-configurable via Options Flow, not hardcoded
The original design hardcoded `HIGH_PRIORITY_NAMES = {"Highest", "High"}` in
`const.py`. This was discovered to be **broken** for the target CLDSOLACC
instance, which uses a non-standard priority scheme: **Blocker → Critical →
Major → Minor → Trivial**. The hardcoded set would silently return 0 for the
`high_priority` sensor on every poll.

**Decision:** make high-priority names user-configurable via the Options Flow.

**Implementation:**
- `GET /rest/api/3/priority` is fetched at setup time alongside `/field`
  (cheap, no pagination, ~10 lines in `api.py`).
- The full priority list is presented as a multi-select in the Options Flow.
- Selected names stored as `OPT_HIGH_PRIORITY_NAMES` (list[str]) in options.
- Default: `["Blocker", "Critical"]` — correct for the CLDSOLACC instance and
  semantically appropriate ("things on fire") for most instances.
- `aggregator.aggregate()` accepts `high_priority_names: set[str]` as a
  parameter instead of importing a hardcoded constant — keeps the pure layer
  HA-free and testable with any priority scheme.
- `const.py` retains `DEFAULT_HIGH_PRIORITY_NAMES = ["Blocker", "Critical"]`
  as the fallback when options haven't been configured yet.

**Affected tasks:** 2 (const), 4 (aggregator), 7 (api — add `get_priorities`),
9 (coordinator — pass names into aggregate), 11 (options flow — multi-select).

### "Newly assigned" mechanism: key set-diff, not JQL changelog
Compare current open-assigned issue-key set vs. the previous poll's set;
`new = current - previous`. Chosen over JQL changelog (`assignee changed to
currentUser() after -1d`) because it's self-contained and needs no special Jira
features. First poll reports 0 (treats `previous = current`) to avoid a
startup flood. This is the one piece of business logic that needs memory, so it
lives in the **coordinator**, not the stateless aggregator
(`newly_assigned.py` tracker, owned by the coordinator).

### Persistence: "Option 2" (shutdown-write + load + hourly checkpoint)
Considered: (1) write-on-shutdown only, (2) shutdown + periodic checkpoint,
(3) write-every-poll. Chose **2**. Shutdown-only loses state on hard crashes
(power loss, OOM, kill -9) because `homeassistant_stop` doesn't fire. Option 2
adds an hourly checkpoint (`poll_count % CHECKPOINT_EVERY`) for ~5 extra lines,
capping hard-crash loss to ≤1h. Uses HA's `Store` helper. Corrupt/missing store
on load → start fresh, never block startup.

### Custom work item types: dynamic via `by_type`, no hardcoding
Jira's API doesn't distinguish built-in vs. custom issue types. `by_type`
buckets on `issuetype.name`, so custom types (e.g. **Migration**, **Deal**)
appear automatically with no code change; new types show up on the next poll.
They live in the `by_type` attribute (not dedicated sensors) per Shape 1+.

### Duplicate custom-field names: disambiguate in the dropdown
Internally everything keys off the immutable `customfield_xxxxx` ID, so data is
never ambiguous. Only the Options-Flow *label* could collide. When `/field`
returns two customs with the same display name, append the ID to both, e.g.
`Team (customfield_10031)`. `/field` is fetched at setup and when Options opens,
then cached — NOT on every poll (poll works with IDs only).

### Resource constraints (low-powered Mac/VM): not a design driver
CPU per poll is trivial (one HTTPS call + iterating tens of issues); memory is
kilobytes. The only real budget is **Jira Cloud rate limits**, handled by the
single-query, 5-min-interval design. Persistence writes are a few KB — negligible.
Conclusion: do NOT design around the laptop; it's over-spec'd for this.

### Packaging: Tier 1 readiness now, Tier 2 deferred
- **Tier 1 (target now):** repo structured so it's installable via a GitHub URL
  as a HACS "custom repository" — clean `custom_components/jira_work/` layout,
  complete `manifest.json` (`iot_class: cloud_polling`, docs/issue-tracker/
  codeowners/version), `hacs.json`, README, LICENSE, versioned release tags.
  All additive hygiene; zero impact on integration logic.
- **Tier 2 (deferred):** submission to the HACS default store (passes
  `hacs/action`), `home-assistant/brands` entry, translations, `hassfest`,
  broader tests, ongoing maintenance — and OAuth becomes the recommended auth.

---

## How to Resume

1. Read the spec, then the plan.
2. Pick an execution mode (subagent-driven recommended).
3. Start at **Task 1** and work through sequentially; each task is TDD
   (write failing test → run → implement → run → commit).
4. The pure layer (`api.py`, `aggregator.py`, `newly_assigned.py`) must stay
   HA-import-free — Task 14 Step 3 verifies this.

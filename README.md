# YAML-Driven Locust Load Testing Engine

A [Locust](https://locust.io/) locustfile (`Test_Locust.py`) that lets you define entire load test
scenarios in a YAML config instead of writing Python. Point it at a config file, run `locust`, and
you get data-driven, multi-user, multi-host load tests with conditional flows, custom ramp-up
shapes, rate limiting, and one-time setup/teardown — no Python required for day-to-day test authoring.

See [`locust_config_reference.yaml`](./locust_config_reference.yaml) for a fully-documented,
copy-paste-friendly reference of every field. This README explains what the engine does and how
the pieces fit together.

---

## Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Users & Tasks](#users--tasks)
- [Data-Driven Testing (CSV)](#data-driven-testing-csv)
- [Request Payloads](#request-payloads)
- [Extracting Values & Placeholders](#extracting-values--placeholders)
- [Conditional / Branching Flow](#conditional--branching-flow)
- [Rate Limiting](#rate-limiting)
- [Multi-Host Support](#multi-host-support)
- [Custom Load Shapes](#custom-load-shapes)
- [Setup / Teardown Hooks](#setup--teardown-hooks)
- [Logging](#logging)
- [Running the Test](#running-the-test)
- [Known Limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- Python 3.9+
- `pip install locust pyyaml requests`

## Quick Start

1. Copy `locust_config_reference.yaml` to `OrderPlace.yaml` (the engine reads this exact filename
   from the current working directory) and edit it to describe your scenario.
2. Run it:

   ```bash
   locust -f Test_Locust.py --headless -u 50 -r 5 --run-time 5m
   ```

   Or launch the web UI instead of `--headless`:

   ```bash
   locust -f Test_Locust.py
   # then open http://localhost:8089
   ```

3. Watch the console — the engine logs setup/teardown, CSV loading, shape registration, and
   per-request detail (at the right verbosity — see [Logging](#logging)) as the run progresses.

The engine validates your config **at import time**, before any load is generated. A typo or
structural mistake (bad condition syntax, a host-less user, mismatched branches, etc.) fails fast
with a clear error message instead of surfacing as a confusing failure mid-run.

## How It Works

`Test_Locust.py` reads `OrderPlace.yaml`, then dynamically builds real Locust `HttpUser` classes,
`@task` methods, and (optionally) a `LoadTestShape` from it — all in Python's `type()` machinery, so
the rest of Locust (stats, web UI, distributed mode) works exactly as it would for a hand-written
locustfile. Nothing about the YAML format is Locust-specific; it's this engine's own DSL layered on
top.

## Users & Tasks

Each entry under `users:` becomes one Locust `User` class.

```yaml
users:
  - name: Customer_Type_A
    weight: 6                # relative proportion of this user class vs others
    wait_time: [1, 8]        # random think-time in seconds between tasks
    sequential: true         # tasks run in this exact order, looping forever
    tasks:
      - name: "Place Order"
        method: POST
        endpoint: "/orders"
        payload: { qty: 1 }
```

- **`sequential: true`** — tasks run in the listed order, looping back to the start. Add
  `run_once: true` to stop the user (via `StopUser()`) after the last task instead of looping.
- **`sequential: false`** (default) — classic Locust weighted-random task selection.
- A **task with `subtasks:`** is a *chained flow* (e.g. place order → pay for order): all subtasks
  share one `user_context`, so a later step can reference a value an earlier step extracted. A
  failed subtask stops the rest of the chain unless it sets `continue_on_failure: true`.
- A **task without `subtasks:`** (and without `branches:` — see below) is itself a single request
  step, using the same fields described in [Request Payloads](#request-payloads).

## Data-Driven Testing (CSV)

Two independent CSV mechanisms, usable together:

- **Global CSV** (`use_csv`, `csv_file`, `csv_column`, `csv_mode`) — a shared pool of rows (e.g.
  auth tokens) picked per-iteration (`csv_scope: per_iteration`, default) or once per virtual user
  (`csv_scope: per_user`, "sticky" for that user's whole session).
- **Task/subtask-level `CSV_file`** — a separate CSV scoped to just one task or subtask, picked via
  `random.choice` regardless of the global `csv_mode`.

A `transform:` block (trim / lowercase / replace-spaces / suffix) applies to every value pulled from
either kind of CSV before it lands in `user_context`.

## Request Payloads

Exactly one of three ways to build a request body, all supporting `{{placeholder}}` substitution:

| Field | Behavior |
|---|---|
| `payload:` | Inline YAML block. Placeholders substituted after YAML parsing (string leaf values only). |
| `payload_from_file:` | Reads a static JSON file. Placeholders substituted on the **raw text before parsing** — so an unquoted `{{qty}}` can inject a real number/bool, not just a string. |
| `payload_from_csv:` | Reads a CSV row's column value as a **path to a JSON file**, then loads it exactly like `payload_from_file` (same raw-text substitution, same behavior). Shorthand: `payload_from_csv: "rows.csv"` (column defaults to `"payload"`). |

File uploads (`files:` + optional `form:`) build a real multipart request; a same-named JSON key in
`payload` and `form` is stored as `json_<key>` to avoid a silent overwrite.

## Extracting Values & Placeholders

Any step can declare `extract:` to pull a value out of the response and store it in
`user_context` for later steps:

```yaml
extract:
  - from: "json"        # or "headers"
    field: "data.order.id"   # dotted/bracket path, e.g. data.items[0].id
    save_as: "order_id"
```

That value is then available anywhere downstream as `{{order_id}}` — in a later subtask's
`endpoint`, `headers`, `payload`, `params`, `form`, `files.path`, or even `host`. A failed
extraction clears any stale value from a previous loop and marks the step unsuccessful (which, in a
subtask chain, stops the rest of the chain unless `continue_on_failure: true`).

## Conditional / Branching Flow

Two mechanisms, both driven by a small structured condition DSL (deliberately not `eval()`):

```yaml
if: { var: payment_status, op: equals, value: "failed" }
if: { var: order_id, op: exists }
if: { any: [ { var: retry_count, op: gt, value: 3 }, { var: is_vip, op: equals, value: "true" } ] }
```

Supported `op`s: `equals`, `not_equals`, `exists`, `not_exists`, `contains`, `not_contains`, `gt`,
`lt`, `gte`, `lte`, `in`, `not_in`, plus `all` / `any` / `not` combinators. A comparison against a
variable that was never set evaluates to `false` rather than raising.

- **Step-level `if:`** (on a task-without-subtasks, or any subtask) — skip just that one step when
  false. Not treated as a failure; the chain continues.
- **Task-level `branches:`** (instead of `subtasks:`) — pick exactly **one** subtask chain to run,
  based on the first branch whose `if:` is true (or that has no `if:` at all — the default/else,
  which must be listed last):

  ```yaml
  - name: "Handle Payment Result"
    branches:
      - if: { var: payment_status, op: equals, value: "failed" }
        subtasks: [ { method: POST, endpoint: "/refund/initiate" } ]
      - subtasks: [ { method: POST, endpoint: "/shipping/schedule" } ]  # default
  ```
- **Task-level `if:`** also works on any task (single-step, `subtasks`, or `branches` alike) to gate
  the whole thing.

## Rate Limiting

Cap how often a task or step fires — **globally across every concurrent user**, not per-user:

```yaml
rate_limit: 20                                    # shorthand: 20/sec
rate_limit: { rate: 100, per: "minute" }          # full form
rate_limit: { rate: 100, per: "minute", name: "shared_gateway" }  # shared across multiple steps
```

- On a **step**, gates that individual HTTP call.
- On a **task with `subtasks`/`branches`**, gates the whole chain as one unit (e.g. "5 order-flows/sec
  total", not "5 of each subtask/sec"). A skipped task/branch (due to `if:`) doesn't consume budget.
- `name:` lets unrelated steps/tasks share one combined limiter — useful when several different
  flows all hit the same rate-limited downstream dependency.

> **Caveat:** the limiter lives in-process. In a single (`--headless` or web UI) `locust` run this
> is a true global cap. In distributed mode (`--master`/`--worker`), each **worker** process has its
> own independent limiter, so the real combined rate is `(configured rate × number of workers)` —
> divide accordingly for a hard total across a distributed run.

## Multi-Host Support

Three levels of override, checked in this order — step, then user, then global:

```yaml
host: "https://api.example.com"     # global default

users:
  - name: Customer_Type_A
    host: "https://orders.example.com"   # per-user-class override
    tasks:
      - name: "Get Token"
        host: "https://auth.example.com"  # per-step override (supports {{var}})
```

If a user has no host anywhere (no global, no user-level) the engine validates at load time that
**every** one of its tasks/subtasks supplies its own step-level host — otherwise it fails fast
instead of letting Locust error out mid-test on the first request.

## Custom Load Shapes

Define a ramp-up/ramp-down pattern in YAML instead of writing a `LoadTestShape` subclass:

```yaml
shape:
  type: stages
  loop: false                # restart from stage 1 after the last stage, for soak tests
  use_common_options: false  # true = --run-time (-t) still applies on top of the shape
  stages:
    - duration: 60            # cumulative seconds from test start
      users: 10
      spawn_rate: 10
      user_classes: ["Customer_Type_A"]   # optional — restrict this stage to specific users
    - duration: 300
      users: 100
      spawn_rate: 10
```

When a `shape:` is present, Locust hides `-u`/`-r`/`-t` by default — the shape fully controls user
count and spawn rate for the run (add `use_common_options: true` to keep `--run-time` as a hard cap
on top of it).

## Setup / Teardown Hooks

Run **once for the whole test**, not once per user — via Locust's `test_start`/`test_stop` events,
using the exact same step schema as a normal task/subtask:

```yaml
setup:
  - method: POST
    endpoint: "/auth/login"
    payload: { username: "loadtest", password: "..." }
    extract:
      - from: "json"
        field: "data.token"
        save_as: "shared_token"    # copied into EVERY user's context on start

teardown:
  - method: POST
    endpoint: "/cleanup"
    headers:
      authorization: "Bearer {{shared_token}}"
```

- **`setup:`** runs before any users spawn. A failing *required* step (no `continue_on_failure`)
  aborts the whole run before any load is generated.
- **`teardown:`** runs after the test stops. Always best-effort — a failing step is logged and the
  next teardown step still runs regardless.
- In distributed mode, only the master runs these — never duplicated per worker.

## Logging

Uses Python's `logging` module instead of `print()`, so verbosity doesn't cost you anything at
scale unless you turn it up:

```yaml
log_level: "INFO"           # DEBUG | INFO | WARNING | ERROR | CRITICAL
log_file: "engine.log"      # optional — also write to a file
```

| Level | Shows |
|---|---|
| `DEBUG` | Full request/response dumps (also requires `print_request`/`print_response: true` on the step), successful requests, CSV row picks, successful extracts |
| `INFO` *(default, recommended for real runs)* | Setup/lifecycle messages only |
| `WARNING` | Recoverable per-request problems (missing files, failed extracts, skipped requests) |
| `ERROR` | Failed HTTP requests |

`print_request`/`print_response` and `log_level` combine — a step can be left with
`print_request: true` without spamming a normal `INFO` run; nothing shows until `log_level: DEBUG`.

## Running the Test

```bash
# Headless, fixed user count
locust -f Test_Locust.py --headless -u 100 -r 10 --run-time 10m

# Web UI
locust -f Test_Locust.py

# Distributed
locust -f Test_Locust.py --master
locust -f Test_Locust.py --worker --master-host=<master-ip>   # run on each worker
```

The engine reads `OrderPlace.yaml` from the current working directory — run `locust` from wherever
that file lives, or adjust the path in `Test_Locust.py`.

## Known Limitations

- **Rate limiting is per-process**, not per-cluster — see the caveat in
  [Rate Limiting](#rate-limiting).
- **Custom load shapes** currently only support `type: stages`.
- **`payload_from_csv`** treats the CSV column as a *path to a JSON file* (not inline JSON in the
  cell) — this matches the documented behavior, but it's easy to assume otherwise.
- The config filename (`OrderPlace.yaml`) is currently hardcoded in `Test_Locust.py`.

## Troubleshooting

- **"config has no 'users:' section"** — `users:` is missing or empty in the YAML.
- **"User '...' has no host set..."** — no global `host:`, no user-level `host:`, and at least one
  task/subtask for that user has no step-level `host:` either.
- **"... cannot have both 'subtasks' and 'branches'"** — pick one; they're mutually exclusive on a
  task.
- **A branch never seems to run** — check branch order: branches are evaluated top-to-bottom and the
  *first* match wins, so a default (no `if:`) branch listed before a specific one will shadow it.
- **Nothing shows up even with `print_request: true`** — set `log_level: "DEBUG"`; the two controls
  combine (see [Logging](#logging)).
- **Setup step fails and the whole run stops immediately** — that's by design (a required setup
  step failing aborts the run before load begins). Add `continue_on_failure: true` on that step if
  it's fine for the run to continue anyway.

---

For the complete, field-by-field reference with inline explanations for every option, see
[`locust_config_reference.yaml`](./locust_config_reference.yaml).

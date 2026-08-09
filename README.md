# Locust YAML Engine

A configuration-driven Locust load-testing engine. Define complex multi-step user flows, CSV-driven data, multi-host targeting, response extraction, file uploads, and custom load shapes entirely in YAML — with almost no Python required.

The engine reads a single YAML file and dynamically builds Locust `HttpUser` classes (sequential or probabilistic), tasks, and an optional `LoadTestShape`.

---

## Features

| Feature | Description |
|---------|-------------|
| **YAML-driven users & tasks** | Define entire scenarios in config — no hand-written Locust tasks needed |
| **Sequential multi-step flows** | Chain requests (e.g. place order → confirm payment) that share context |
| **Non-sequential (classic Locust)** | Weighted random task selection |
| **CSV data injection** | Global token/identity CSVs + per-task/per-subtask CSVs |
| **Placeholder substitution** | `{{Token}}`, `{{order_id}}`, etc. in endpoints, headers, payloads, hosts |
| **Response extraction** | Pull values from JSON body or headers and reuse in later steps |
| **Payload sources** | Inline JSON, static file, or CSV that points to JSON files |
| **Multipart file uploads** | Attach files with form fields |
| **Multi-host support** | Global host, per-user-class host, or per-step host override |
| **Custom load shapes** | Staged ramp-up / spike / soak patterns defined in YAML |
| **Controlled logging** | DEBUG dumps only when you ask for them; clean INFO for real runs |
| **run_once** | Sequential users that stop after one full pass |
| **csv_scope** | Sticky per-user CSV row vs fresh row every iteration |

---

## Requirements

- Python 3.8+
- [Locust](https://locust.io/) (`pip install locust`)
- PyYAML (`pip install pyyaml`)

```bash
pip install locust pyyaml
```

---

## Quick Start

1. **Copy the engine script** and rename or keep `Test_Locust.py`.
2. **Create your config** (e.g. `OrderPlace.yaml`) by copying sections from the reference file.
3. **Prepare any CSVs / payload JSON files** referenced in the config.
4. **Run Locust**:

```bash
# Headless example
locust -f Test_Locust.py --headless -u 50 -r 10 -t 5m

# Or open the web UI
locust -f Test_Locust.py
```

> **Note:** The script currently hard-codes `OrderPlace.yaml` as the config file. Change the path near the top of `Test_Locust.py` if you use a different name:

```python
with open("OrderPlace.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
```

When a custom `shape:` block is present in the YAML, Locust ignores `-u` / `-r` / `-t` by default (the shape fully controls user count and spawn rate). Set `use_common_options: true` under `shape:` if you still want `--run-time` to act as a hard cap.

---

## Configuration Overview

The engine expects a single YAML file. See **`locust_config_reference.yaml`** for a fully annotated example of every supported field.

### Top-level keys

| Key | Purpose |
|-----|---------|
| `host` | Default base URL for all users that do not override it |
| `api_key` | Optional value you can anchor (`&name`) and reuse via alias (`*name`) |
| `log_level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` (default `INFO`) |
| `log_file` | Optional extra log file path |
| `use_csv` | Master switch for the global CSV feature |
| `csv_file` | One or more CSV paths (list or string) |
| `csv_mode` | `"sequential"` (round-robin) or `"random"` (default) |
| `csv_column` | Column name(s) copied into each user’s context |
| `transform` | Optional rules applied to every CSV value (trim, lowercase, etc.) |
| `users` | List of user-class definitions (required) |
| `shape` | Optional custom load-shape definition |

### User definition

```yaml
- name: Customer_Type_A          # becomes Customer_Type_AUser
  weight: 6                      # relative proportion of this class
  wait_time: [1, 8]              # think time [min, max] seconds
  sequential: true               # true = ordered flow; false = weighted random
  csv_scope: "per_iteration"     # or "per_user" (sticky row for the whole session)
  run_once: false                # if true + sequential, stop after one full pass
  host: "https://other.example.com"   # optional per-user override
  tasks: [...]
```

### Task / Subtask (HTTP step)

A task can either:

- Contain a **`subtasks`** list → multi-step chain that shares `user_context`, or
- Be a **single request** itself (all the fields below live directly on the task).

Common step fields:

| Field | Description |
|-------|-------------|
| `method` | `GET`, `POST`, `PUT`, `DELETE`, … |
| `endpoint` | Path (or full path after host) |
| `request_name` | Label shown in Locust stats |
| `host` | Optional per-step host override (supports `{{var}}`) |
| `headers` / `params` | Dicts; placeholders substituted |
| `payload` | Inline JSON body |
| `payload_from_file` | Path to a JSON file (placeholders substituted) |
| `payload_from_csv` | `{file: …, column: "payload"}` or shorthand string — column value is treated as a path to a JSON file |
| `form` | Form fields (used with or without files) |
| `files` | List of `{field, path, mime}` for multipart uploads |
| `extract` | List of `{from: json\|headers, field, save_as}` |
| `print_request` / `print_response` | Enable debug dumps (only visible when `log_level: DEBUG`) |
| `continue_on_failure` | If `true`, later subtasks still run even if this one fails |
| `CSV_file` | Optional per-task or per-subtask CSV (rows always picked randomly) |

### Placeholders

Any `{{name}}` appearing in `endpoint`, `headers`, `params`, `payload`, `form`, `files.path`, or step-level `host` is replaced from the current user’s `user_context`.

Context is populated by:

1. Global CSV columns (`csv_column`)
2. Task-/subtask-level `CSV_file` columns
3. Values extracted by earlier steps (`extract` → `save_as`)

### Custom load shape

```yaml
shape:
  type: stages                 # only "stages" is supported
  loop: false                  # restart from stage 1 after the last duration?
  use_common_options: false    # allow Locust -t / etc. on top of the shape
  stages:
    - duration: 60             # cumulative seconds from test start
      users: 10
      spawn_rate: 10
      user_classes: ["Customer_Type_A"]   # optional restriction
    - duration: 180
      users: 50
      spawn_rate: 10
    # …
```

Durations are **cumulative**. Stages must be strictly increasing.

---

## Logging

The engine uses its own logger (`locust_yaml_engine`), separate from Locust’s built-in logging.

| Level | What you see |
|-------|--------------|
| `DEBUG` | Full request/response dumps (when `print_request` / `print_response` are true), successful extracts, CSV picks, OK requests |
| `INFO` | Setup messages, CSV loads, shape registration, `run_once` completion |
| `WARNING` | Missing files, failed extracts, skipped requests |
| `ERROR` | Non-2xx/3xx HTTP responses |

Recommendation for real load runs: `log_level: INFO` and turn `print_request` / `print_response` off (or leave them on — they only emit under DEBUG).

---

## Multi-Host Support

Three levels (most specific wins):

1. **Global** `host:` at the top of the YAML
2. **Per-user-class** `host:` under a user
3. **Per-step** `host:` on an individual task or subtask (supports `{{var}}`)

If a user has neither a global nor a user-level host, every one of its steps **must** declare its own `host:`. The engine validates this at startup and fails fast with a clear error.

---

## File Layout Example

```
project/
├── Test_Locust.py                 # the engine
├── OrderPlace.yaml                # your real config
├── locust_config_reference.yaml   # annotated reference (do not run as-is)
├── tokenV1.csv                    # global identity / tokens
├── order_payloads.csv             # points to JSON payload files
├── payloads/
│   ├── order_001.json
│   └── order_002.json
└── assets/
    └── sample_avatar.jpg
```

---

## Tips & Gotchas

- **Stale extracts** – The engine clears every `save_as` key belonging to a task before each run of that task, so a failed earlier step cannot leak an old value into a later step.
- **`continue_on_failure`** – Defaults to `false`. A failed subtask (bad status **or** missing extract) stops the rest of the chain.
- **`payload_from_csv`** – The CSV column value is treated as a **path to a JSON file**, not as the JSON body itself. Row selection now respects the global `csv_mode`.
- **Task-level / subtask-level CSVs** – Always picked with `random.choice`, independent of global `csv_mode`.
- **Shape + CLI** – When a shape is defined, `-u`/`-r`/`-t` are hidden unless `use_common_options: true`.
- **YAML anchors** – Useful for shared secrets (`api_key: &shared_token "…"` → `sxsrf: *shared_token`).

---

## Reference

The file **`locust_config_reference.yaml`** contains a complete, heavily commented example of every supported feature. Copy only the sections you need into your real config.

---

## License / Attribution

This engine is a thin YAML-driven wrapper around [Locust](https://locust.io/). Use it under the same terms as your Locust installation and any internal policies that apply to your load tests.

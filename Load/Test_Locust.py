import yaml
import csv
import json
import os
import random
import re
from itertools import cycle
from locust import HttpUser, task, between, SequentialTaskSet, LoadTestShape
from locust.exception import StopUser

# ------------------------------
# Load YAML configuration
# ------------------------------
with open("OrderPlace.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

global_host = config.get("host")
use_csv = config.get("use_csv", False)
csv_files = config.get("csv_file", [])
csv_mode = config.get("csv_mode", "random")
csv_columns = config.get("csv_column", [])
if isinstance(csv_columns, str):
    csv_columns = [csv_columns]

if isinstance(csv_files, str):
    csv_files = [csv_files]

transform_rules = config.get("transform", {})

# ------------------------------
# Custom load shape config (optional)
# ------------------------------
shape_config = config.get("shape")


def validate_shape_config(shape_cfg, user_names):
    """
    Validates the optional top-level "shape:" block.
    Raises ValueError with a clear message on any problem instead of
    letting a bad shape silently produce a flat/no-op ramp at runtime.
    """
    if shape_cfg is None:
        return None

    shape_type = shape_cfg.get("type", "stages")
    if shape_type != "stages":
        raise ValueError(
            f"shape.type '{shape_type}' is not supported yet — only 'stages' is currently implemented."
        )

    stages = shape_cfg.get("stages")
    if not stages or not isinstance(stages, list):
        raise ValueError("shape.stages must be a non-empty list.")

    last_duration = 0
    for i, stage in enumerate(stages):
        duration = stage.get("duration")
        users = stage.get("users")
        spawn_rate = stage.get("spawn_rate")

        if duration is None or not isinstance(duration, (int, float)) or duration <= 0:
            raise ValueError(f"shape.stages[{i}].duration must be a positive number.")
        if i > 0 and duration <= last_duration:
            raise ValueError(
                f"shape.stages[{i}].duration ({duration}) must be strictly greater than "
                f"the previous stage's duration ({last_duration}) — durations are cumulative "
                f"seconds from test start, not per-stage lengths."
            )
        last_duration = duration

        if users is None or not isinstance(users, (int, float)) or users < 0:
            raise ValueError(f"shape.stages[{i}].users must be a non-negative number.")
        if spawn_rate is None or not isinstance(spawn_rate, (int, float)) or spawn_rate <= 0:
            raise ValueError(f"shape.stages[{i}].spawn_rate must be a positive number.")

        classes = stage.get("user_classes")
        if classes:
            if not isinstance(classes, list):
                raise ValueError(f"shape.stages[{i}].user_classes must be a list of user names.")
            for c in classes:
                if c not in user_names:
                    raise ValueError(
                        f"shape.stages[{i}].user_classes references unknown user '{c}'. "
                        f"Known users: {sorted(user_names)}"
                    )

    return shape_cfg


_known_user_names = {u.get("name") for u in config.get("users", []) if u.get("name")}
if shape_config is not None:
    shape_config = validate_shape_config(shape_config, _known_user_names)
    print(f"📈 Loaded custom load shape: {len(shape_config['stages'])} stage(s), "
          f"loop={shape_config.get('loop', False)}")


def safe_dict_reader(file_obj):
    reader = csv.DictReader(file_obj)
    if reader.fieldnames:
        reader.fieldnames = [fn.lstrip("\ufeff").strip() for fn in reader.fieldnames]
    return reader


# ------------------------------
# Transformation function
# ------------------------------
def apply_transforms(value, rules):
    if not isinstance(value, str):
        return value
    v = value.strip() if rules.get("trim", True) else value
    if rules.get("replace_spaces_with"):
        v = v.replace(" ", rules["replace_spaces_with"])
    if rules.get("lowercase", False):
        v = v.lower()
    if rules.get("suffix"):
        v += rules.get("suffix", "")
    return v

# ------------------------------
# Placeholder replacement
# ------------------------------
def replace_placeholders(item, context):
    if isinstance(item, dict):
        return {k: replace_placeholders(v, context) for k, v in item.items()}
    elif isinstance(item, list):
        return [replace_placeholders(v, context) for v in item]
    elif isinstance(item, str):
        for key, val in context.items():
            item = item.replace(f"{{{{{key}}}}}", str(val))
        return item
    return item

# ------------------------------
# Deep JSON extraction
# ------------------------------
def deep_get(dictionary, path, default=None):
    keys = re.split(r"[.\[\]]+", path.strip("."))
    for key in keys:
        if not key:
            continue
        if isinstance(dictionary, dict):
            dictionary = dictionary.get(key, default)
        elif isinstance(dictionary, list) and key.isdigit():
            dictionary = dictionary[int(key)]
        else:
            return default
    return dictionary

# ------------------------------
# Load payload from file
# ------------------------------
def load_payload_from_file(filepath, context):
    if not os.path.exists(filepath):
        print(f"⚠️ Payload file not found: {filepath}")
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read().strip()
        raw = replace_placeholders(raw, context)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print(f"⚠️ Invalid JSON format in file: {filepath}")
            return None

# ------------------------------
# Collect all "save_as" keys a task (and its subtasks) can write,
# so we can reset them before each run and avoid stale values
# leaking into a later step if an earlier step fails.
# ------------------------------
def collect_extract_keys(task_config):
    keys = set()
    for ex in task_config.get("extract", []) or []:
        if ex.get("save_as"):
            keys.add(ex["save_as"])
    for sub in task_config.get("subtasks", []) or []:
        for ex in sub.get("extract", []) or []:
            if ex.get("save_as"):
                keys.add(ex["save_as"])
    return keys


# ------------------------------
# Execute a single HTTP step
# Returns True if the step is considered successful (response.ok and,
# if an extract was declared, the value was actually found), False otherwise.
# ------------------------------
def execute_request(self, step):
    method = step["method"]
    endpoint = step["endpoint"]

    req_headers = replace_placeholders(step.get("headers", {}), self.user_context)
    req_params = replace_placeholders(step.get("params", {}), self.user_context)
    req_payload = None

    # A step that declares payload_from_file / payload_from_csv REQUIRES a
    # payload to make sense. If loading fails, we skip the request entirely
    # instead of silently sending it with an empty body.
    payload_required = "payload_from_file" in step or "payload_from_csv" in step

    # load JSON payload
    if "payload_from_file" in step:
        req_payload = load_payload_from_file(step["payload_from_file"], self.user_context)
    elif "payload_from_csv" in step:
        csv_info = step["payload_from_csv"]
        if isinstance(csv_info, str):
            filepath = csv_info
            column_name = "payload"
        else:
            filepath = csv_info.get("file")
            column_name = csv_info.get("column", "payload")

        json_file_name = load_payload_from_csv_cache(filepath, column_name)
        if json_file_name:
            req_payload = json_file_name
    elif "payload" in step:
        req_payload = replace_placeholders(step["payload"], self.user_context)

    if payload_required and req_payload is None:
        print(f"⛔ SKIPPING request {step.get('method')} {step.get('endpoint')} — "
              f"required payload could not be loaded.")
        return False

    endpoint_with_values = replace_placeholders(endpoint, self.user_context)
    request_name = step.get("request_name")

    # Optional per-step host override (case C from the multi-host plan):
    # lets a single task/subtask hit a different service than the rest of
    # its user class (e.g. an auth microservice before the main API).
    # Goes through the same placeholder substitution as endpoint, so
    # CSV-driven hosts like "{{region}}.api.example.com" work too.
    step_host = step.get("host")
    if step_host:
        step_host = replace_placeholders(step_host, self.user_context).rstrip("/")
        request_url = f"{step_host}/{endpoint_with_values.lstrip('/')}"
    else:
        # No override: pass the relative path through as-is so Locust's
        # HttpSession applies the user class's own "host" (see per-user
        # host resolution in the class-building loop below).
        request_url = endpoint_with_values

    send_kwargs = {
        "headers": req_headers,
        "params": req_params,
    }

    file_objs = []
    try:
        if "files" in step and step["files"]:
            files_conf = step["files"]
            files_payload = []

            for f in files_conf:
                field = f.get("field")
                raw_path = f.get("path")
                mime = f.get("mime", None)
                path = replace_placeholders(raw_path, self.user_context) if raw_path else None
                if not path or not os.path.exists(path):
                    print(f"⚠️ File not found: {path} (field: {field})")
                    continue

                fobj = open(path, "rb")
                file_objs.append(fobj)
                filename = os.path.basename(path)

                if mime:
                    files_payload.append((field, (filename, fobj, mime)))
                else:
                    files_payload.append((field, (filename, fobj)))

            form_payload = {}

            if "form" in step and isinstance(step["form"], dict):
                form_payload = replace_placeholders(step["form"], self.user_context)

            if req_payload is not None and isinstance(req_payload, dict):
                for k, v in req_payload.items():
                    if k not in form_payload:
                        form_payload[k] = v
                    else:
                        form_payload[f"json_{k}"] = v

            send_kwargs["files"] = files_payload
            send_kwargs["data"] = form_payload

            if step.get("print_request", False):
                print("\n===== REQUEST DEBUG INFO =====")
                print(f"[REQUEST] {method.upper()} {request_url}")
                print("Headers:")
                print(json.dumps(req_headers, indent=2))
                print("Query Params:")
                print(json.dumps(req_params, indent=2))
                if req_payload is not None:
                    print("JSON Payload:")
                    try:
                        print(json.dumps(req_payload, indent=2))
                    except:
                        print(req_payload)
                print("Form Data:")
                print(json.dumps(send_kwargs["data"], indent=2))
                print("Files:")
                for (field, meta) in send_kwargs["files"]:
                    filename = meta[0]
                    mime = meta[2] if len(meta) >= 3 else "N/A"
                    print(f"  - field: {field}, filename: {filename}, mime: {mime}")
                print("===== END REQUEST INFO =====\n")

            response = self.client.request(method.upper(), request_url, name=request_name, **send_kwargs)

        else:
            if "form" in step and step["form"]:
                data_payload = replace_placeholders(step["form"], self.user_context)

                if step.get("print_request", False):
                    print("\n===== REQUEST DEBUG INFO =====")
                    print(f"[REQUEST] {method.upper()} {request_url}")
                    print("Headers:")
                    print(json.dumps(req_headers, indent=2))
                    print("Query Params:")
                    print(json.dumps(req_params, indent=2))
                    print("Form Data:")
                    print(json.dumps(data_payload, indent=2))
                    print("===== END REQUEST INFO =====\n")

                response = self.client.request(
                    method.upper(),
                    request_url,
                    headers=req_headers,
                    params=req_params,
                    data=data_payload,
                    name=request_name
                )
            elif req_payload is not None:
                if step.get("print_request", False):
                    print("\n===== REQUEST DEBUG INFO =====")
                    print(f"[REQUEST] {method.upper()} {request_url}")
                    print("Headers:")
                    print(json.dumps(req_headers, indent=2))
                    print("Query Params:")
                    print(json.dumps(req_params, indent=2))
                    print("JSON Payload:")
                    print(json.dumps(req_payload, indent=2))
                    print("===== END REQUEST INFO =====\n")

                response = self.client.request(
                    method.upper(),
                    request_url,
                    headers=req_headers,
                    params=req_params,
                    json=req_payload,
                    name=request_name
                )
            else:
                if step.get("print_request", False):
                    print("\n===== REQUEST DEBUG INFO =====")
                    print(f"[REQUEST] {method.upper()} {request_url}")
                    print("Headers:")
                    print(json.dumps(req_headers, indent=2))
                    print("Query Params:")
                    print(json.dumps(req_params, indent=2))
                    print("(no body)")
                    print("===== END REQUEST INFO =====\n")

                response = self.client.request(
                    method.upper(),
                    request_url,
                    headers=req_headers,
                    params=req_params,
                    name=request_name
                )

        if step.get("print_response"):
            print(f"\n[RESPONSE] {method} {request_url}")
            print(f"Status: {response.status_code}")
            try:
                print(json.dumps(response.json(), indent=2))
            except:
                print(response.text[:300])

        step_ok = bool(response.ok)

        if not response.ok:
            print(f"[❌ ERROR] {method} {request_url} -> {response.status_code}")
        else:
            print(f"[✅ OK] {method} {request_url} -> {response.status_code}")

        if "extract" in step:
            for ex in step["extract"]:
                source = ex.get("from")
                field = ex.get("field")
                save_as = ex.get("save_as")
                value = None

                if source == "json":
                    try:
                        value = deep_get(response.json(), field)
                    except:
                        pass
                elif source == "headers":
                    value = response.headers.get(field)

                if value is not None and value != "":
                    self.user_context[save_as] = value
                    print(f"[EXTRACTED] {save_as} = {value}")
                else:
                    # Extraction failed: make sure no stale value from a
                    # previous iteration lingers in context, and mark this
                    # step as unsuccessful so dependent subtasks can be skipped.
                    self.user_context.pop(save_as, None)
                    print(f"⚠️ [EXTRACT FAILED] Could not extract '{save_as}' "
                          f"(from={source}, field={field}) — value not found.")
                    step_ok = False

        return step_ok

    finally:
        for f in file_objs:
            try:
                f.close()
            except:
                pass

# ------------------------------
# Load global combined CSVs
# ------------------------------
csv_data = []
csv_cycle = None
if use_csv and csv_files:
    for fpath in csv_files:
        try:
            with open(fpath, newline="", encoding="utf-8") as f:
                reader = safe_dict_reader(f)
                rows = [row for row in reader]
                csv_data.extend(rows)
                print(f"📂 Loaded global CSV file: {fpath} ({len(rows)} rows)")
        except Exception as e:
            print(f"⚠️ Could not load {fpath}: {e}")
    if csv_mode == "sequential" and csv_data:
        csv_cycle = cycle(csv_data)
else:
    print("⚠️ CSV usage disabled or no file provided.")

# ------------------------------
# Preload task & subtask CSVs
# ------------------------------
task_csv_cache = {}

for user in config.get("users", []):
    for task_cfg in user.get("tasks", []):
        csv_task_file = task_cfg.get("CSV_file")
        if csv_task_file and os.path.exists(csv_task_file):
            try:
                with open(csv_task_file, newline="", encoding="utf-8") as f:
                    reader = safe_dict_reader(f)
                    rows = [row for row in reader]
                    task_csv_cache[csv_task_file] = rows
                    print(f"📂 Preloaded task CSV: {csv_task_file} ({len(rows)} rows)")
            except Exception as e:
                print(f"⚠️ Could not preload {csv_task_file}: {e}")

        for sub in task_cfg.get("subtasks", []):
            sub_csv_file = sub.get("CSV_file")
            if sub_csv_file and os.path.exists(sub_csv_file) and sub_csv_file not in task_csv_cache:
                try:
                    with open(sub_csv_file, newline="", encoding="utf-8") as f:
                        reader = safe_dict_reader(f)
                        rows = [row for row in reader]
                        task_csv_cache[sub_csv_file] = rows
                        print(f"📂 Preloaded subtask CSV: {sub_csv_file} ({len(rows)} rows)")
                except Exception as e:
                    print(f"⚠️ Could not preload {sub_csv_file}: {e}")

# ------------------------------
# Preload payload CSVs
# ------------------------------
payload_csv_cache = {}

for user in config.get("users", []):
    for task_cfg in user.get("tasks", []):
        if "payload_from_csv" in task_cfg:
            csv_info = task_cfg["payload_from_csv"]
            filepath = csv_info if isinstance(csv_info, str) else csv_info.get("file")
            if filepath and os.path.exists(filepath):
                try:
                    with open(filepath, newline="", encoding="utf-8") as f:
                        reader = safe_dict_reader(f)
                        payload_csv_cache[filepath] = [row for row in reader]
                        print(f"📂 Preloaded payload CSV (task): {filepath} ({len(payload_csv_cache[filepath])} rows)")
                except Exception as e:
                    print(f"⚠️ Could not preload payload CSV {filepath}: {e}")

        for sub in task_cfg.get("subtasks", []):
            if "payload_from_csv" in sub:
                csv_info = sub["payload_from_csv"]
                filepath = csv_info if isinstance(csv_info, str) else csv_info.get("file")
                if filepath and os.path.exists(filepath):
                    try:
                        with open(filepath, newline="", encoding="utf-8") as f:
                            reader = safe_dict_reader(f)
                            payload_csv_cache[filepath] = [row for row in reader]
                            print(f"📂 Preloaded payload CSV (subtask): {filepath} ({len(payload_csv_cache[filepath])} rows)")
                    except Exception as e:
                        print(f"⚠️ Could not preload payload CSV {filepath}: {e}")

# ------------------------------
# Load payload from CSV cache (FIXED for JSON filename)
# Row selection now honors the global csv_mode ("sequential" vs "random"),
# same as the token CSV, instead of always being random.
# ------------------------------
payload_csv_cycles = {}


def load_payload_from_csv_cache(filepath, column_name="payload"):
    if filepath not in payload_csv_cache:
        print(f"⚠️ Payload CSV not preloaded: {filepath}")
        return None

    rows = [r for r in payload_csv_cache[filepath] if r.get(column_name)]
    if not rows:
        print(f"⚠️ No valid rows found in {filepath}")
        return None

    if csv_mode == "sequential":
        cache_key = (filepath, column_name)
        if cache_key not in payload_csv_cycles:
            payload_csv_cycles[cache_key] = cycle(rows)
        selected = next(payload_csv_cycles[cache_key])
    else:
        selected = random.choice(rows)

    json_file_name = selected.get(column_name)
    if not json_file_name or not os.path.exists(json_file_name):
        print(f"⚠️ JSON file not found: {json_file_name}")
        return None

    try:
        with open(json_file_name, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Invalid JSON in file {json_file_name}: {e}")
        return None

# ------------------------------
# Task factory
# ------------------------------
def make_task(task_config, stop_after=False):
    @task
    def _t(self):
        if not hasattr(self, "user_context"):
            self.user_context = {}

        csv_task_file = task_config.get("CSV_file")

        if csv_task_file and csv_task_file in task_csv_cache:
            rows = task_csv_cache[csv_task_file]
            if rows:
                row = random.choice(rows)
                for k, v in row.items():
                    self.user_context[k] = apply_transforms(v, transform_rules)
                print(f"[CSV TASK] Picked row from {csv_task_file}: {row}")

        elif use_csv and csv_data and not self.user_context.get("_csv_sticky"):
            # Skipped when csv_scope: "per_user" already assigned a sticky
            # row for this virtual user in on_start (see SeqFlow.on_start).
            if csv_mode == "random":
                row = random.choice(csv_data)
            else:
                row = next(csv_cycle)
            for col in csv_columns:
                if col in row:
                    self.user_context[col] = apply_transforms(row[col], transform_rules)

        # Reset any keys this task/subtasks could produce via "extract" so a
        # failed step this iteration can't leak a stale value from a
        # previous iteration into a later step (e.g. a stale order_id).
        for key in collect_extract_keys(task_config):
            self.user_context.pop(key, None)

        if "subtasks" in task_config:
            print(f"\n▶ Executing combined task: {task_config.get('name', 'Unnamed Task')}")
            for sub in task_config["subtasks"]:

                sub_csv_file = sub.get("CSV_file")
                if sub_csv_file and sub_csv_file in task_csv_cache:
                    rows = task_csv_cache[sub_csv_file]
                    if rows:
                        row = random.choice(rows)
                        for k, v in row.items():
                            self.user_context[k] = apply_transforms(v, transform_rules)
                        print(f"[CSV SUBTASK] Picked row from {sub_csv_file}: {row}")

                success = execute_request(self, sub)

                if not success and not sub.get("continue_on_failure", False):
                    print(f"⛔ Stopping chain for task '{task_config.get('name', 'Unnamed Task')}' "
                          f"— subtask {sub.get('method')} {sub.get('endpoint')} failed "
                          f"(set continue_on_failure: true on the subtask to override).")
                    break
        else:
            execute_request(self, task_config)

        if stop_after:
            # NOTE: on_stop() on a SequentialTaskSet only fires on an
            # explicit interrupt/shutdown — it does NOT fire automatically
            # just because you reached the end of the task list (a
            # SequentialTaskSet loops back to the start forever otherwise).
            # Raising StopUser() here, right after the last task in the
            # sequence, is what actually makes "run_once" work.
            print("🛑 run_once: sequence complete, stopping this user.")
            raise StopUser()

    return _t

# ------------------------------
# Build Users from YAML (Updated for weight)
# ------------------------------
for user in config["users"]:
    wait_min, wait_max = user["wait_time"]

    # ------------------------------
    # Per-user host resolution (multi-host support, case A)
    # Falls back to the global "host" if this user doesn't declare its own.
    # ------------------------------
    user_host = user.get("host", global_host)

    if user_host:
        if not (user_host.startswith("http://") or user_host.startswith("https://")):
            raise ValueError(
                f"User '{user['name']}' has an invalid host '{user_host}' — "
                f"it must start with http:// or https://."
            )
    else:
        # No user-level host AND no global host. This is only safe if
        # every task/subtask for this user supplies its own step-level
        # "host" (case C) — otherwise Locust would only fail loudly at
        # the first request, mid-test, so we check that here instead.
        def _step_has_host(s):
            return bool(s.get("host"))

        all_steps_have_host = True
        for t in user.get("tasks", []):
            if "subtasks" in t:
                if not all(_step_has_host(s) for s in t["subtasks"]):
                    all_steps_have_host = False
                    break
            elif not _step_has_host(t):
                all_steps_have_host = False
                break

        if not all_steps_have_host:
            raise ValueError(
                f"User '{user['name']}' has no host set (no global 'host:', no "
                f"user-level 'host:'), and at least one of its tasks/subtasks "
                f"doesn't declare its own step-level 'host:' either. Set one of "
                f"these so requests have somewhere to go."
            )
        else:
            print(f"ℹ️ User '{user['name']}' has no default host — relying entirely "
                  f"on step-level 'host:' overrides for all its requests.")

    # Flag (don't fail) a user-level host that's fully shadowed by
    # step-level overrides on every single task — likely dead config.
    if user_host and user.get("host"):
        def _step_has_host(s):
            return bool(s.get("host"))

        all_steps_override = True
        for t in user.get("tasks", []):
            if "subtasks" in t:
                if not all(_step_has_host(s) for s in t["subtasks"]):
                    all_steps_override = False
                    break
            elif not _step_has_host(t):
                all_steps_override = False
                break

        if all_steps_override:
            print(f"⚠️ User '{user['name']}' sets its own 'host:' ({user_host}), but "
                  f"every one of its tasks also sets a step-level 'host:' — the "
                  f"user-level host is never actually used. Remove one or the other.")

    if user.get("sequential", False):
        # SequentialTaskSet: tasks run in defined order, weight does not apply
        run_once = user.get("run_once", False)
        raw_tasks = user["tasks"]
        if run_once and raw_tasks:
            task_list = [make_task(t) for t in raw_tasks[:-1]] + [
                make_task(raw_tasks[-1], stop_after=True)
            ]
        else:
            task_list = [make_task(t) for t in raw_tasks]

        # csv_scope: "per_user" (default: "per_iteration") — assign a single
        # CSV row (e.g. one token) once per virtual user instead of a fresh
        # one every time the sequence loops.
        csv_scope = user.get("csv_scope", "per_iteration")

        class SeqFlow(SequentialTaskSet):
            tasks = task_list

            def on_start(self):
                self.user_context = {}
                if csv_scope == "per_user" and use_csv and csv_data:
                    row = random.choice(csv_data) if csv_mode == "random" else next(csv_cycle)
                    for col in csv_columns:
                        if col in row:
                            self.user_context[col] = apply_transforms(row[col], transform_rules)
                    self.user_context["_csv_sticky"] = True
                    print(f"[CSV STICKY] Assigned once for this user: "
                          f"{ {c: self.user_context.get(c) for c in csv_columns} }")

            def on_stop(self):
                # Best-effort cleanup hook. NOTE: this does NOT fire just
                # because the task list finished one loop — see run_once/
                # stop_after in make_task() for the mechanism that actually
                # stops a user after a single pass.
                pass

        globals()[f"{user['name'].capitalize()}User"] = type(
            f"{user['name'].capitalize()}User",
            (HttpUser,),
            {
                "tasks": [SeqFlow],
                "wait_time": between(wait_min, wait_max),
                "weight": user.get("weight", 1),
                "host": user_host,
            },
        )
    else:
        # Non-sequential: Locust-style weight (probabilistic)
        task_funcs = []
        for t in user["tasks"]:
            task_func = make_task(t)
            # Assign weight for Locust to pick tasks probabilistically
            task_func.locust_task_weight = t.get("weight", 1)
            task_funcs.append(task_func)

        globals()[f"{user['name'].capitalize()}User"] = type(
            f"{user['name'].capitalize()}User",
            (HttpUser,),
            {
                "tasks": task_funcs,
                "wait_time": between(wait_min, wait_max),
                "weight": user.get("weight", 1),
                "host": user_host,
            },
        )
# ------------------------------
# Build custom LoadTestShape from YAML (optional)
#
# This must run AFTER all *User classes above have been created, since
# stage-level "user_classes" restrictions are resolved against
# globals()[f"{name.capitalize()}User"].
#
# NOTE: when a LoadTestShape is defined, Locust hides -u/-r/-t by default
# (per Locust's own docs) — the shape fully controls user count and spawn
# rate. Set "use_common_options: true" in the YAML shape block if you also
# want --run-time etc. to apply on top of the shape.
# ------------------------------
if shape_config is not None:
    _stages = shape_config["stages"]
    _loop = shape_config.get("loop", False)
    _use_common_options = shape_config.get("use_common_options", False)

    def _resolve_user_classes(names):
        resolved = []
        for n in names:
            cls_name = f"{n.capitalize()}User"
            cls = globals().get(cls_name)
            if cls is not None:
                resolved.append(cls)
            else:
                print(f"⚠️ shape user_classes references '{n}' but no '{cls_name}' was built — skipping it.")
        return resolved or None

    class YamlLoadShape(LoadTestShape):
        use_common_options = _use_common_options

        def tick(self):
            run_time = self.get_run_time()
            total_duration = _stages[-1]["duration"]

            if _loop and total_duration > 0:
                run_time = run_time % total_duration
            elif run_time >= total_duration:
                # Non-looping shape: stop the test once the last stage's
                # duration has elapsed.
                return None

            for stage in _stages:
                if run_time < stage["duration"]:
                    users = stage["users"]
                    spawn_rate = stage["spawn_rate"]
                    class_names = stage.get("user_classes")

                    if class_names:
                        resolved_classes = _resolve_user_classes(class_names)
                        if resolved_classes:
                            return (users, spawn_rate, resolved_classes)

                    return (users, spawn_rate)

            return None

    print(f"📈 Custom load shape 'YamlLoadShape' registered "
          f"({len(_stages)} stage(s), loop={_loop}, total_duration={_stages[-1]['duration']}s)")

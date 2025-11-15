import yaml
import csv
import json
import os
import random
import re
from itertools import cycle
from locust import HttpUser, task, between, SequentialTaskSet
from locust.exception import StopUser

# ------------------------------
# Load YAML configuration
# ------------------------------
with open("searchtag.yaml", "r", encoding="utf-8") as f:
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
# (existing behavior: file contents must be valid JSON)
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
# Execute a single HTTP step
# - now supports multipart/form-data via `files` + `form` keys in YAML (Option A)
# YAML step examples:
# files:
#   - field: "image"
#     path: "images/1.jpg"
#     mime: "image/jpeg"
#   - field: "gallery[]"
#     path: "images/2.jpg"
#     mime: "image/jpeg"
# form:
#   title: "My Product"
#   desc: "{{description}}"
# ------------------------------
def execute_request(self, step):
    method = step["method"]
    endpoint = step["endpoint"]

    req_headers = replace_placeholders(step.get("headers", {}), self.user_context)
    req_params = replace_placeholders(step.get("params", {}), self.user_context)
    req_payload = None

    # load JSON payloads (existing behavior)
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
        req_payload = load_payload_from_csv_cache(filepath, column_name)
    elif "payload" in step:
        req_payload = replace_placeholders(step["payload"], self.user_context)

    endpoint_with_values = replace_placeholders(endpoint, self.user_context)

    # Build send kwargs depending on whether files are present
    send_kwargs = {
        "headers": req_headers,
        "params": req_params,
    }

    # Prepare multipart if "files" key exists in step (Option A)
    file_objs = []  # to keep references for closing
    try:
        if "files" in step and step["files"]:
            files_conf = step["files"]  # list of {field, path, mime}
            files_payload = []  # use list of tuples to support duplicate field names
            for f in files_conf:
                field = f.get("field")
                raw_path = f.get("path")
                mime = f.get("mime", None)  # optional
                # allow placeholders inside path
                path = replace_placeholders(raw_path, self.user_context) if raw_path else None
                if not path:
                    print(f"⚠️ File entry missing path for field '{field}'")
                    continue
                if not os.path.exists(path):
                    print(f"⚠️ File not found: {path} (field: {field})")
                    continue
                fobj = open(path, "rb")
                file_objs.append(fobj)
                filename = os.path.basename(path)
                if mime:
                    files_payload.append((field, (filename, fobj, mime)))
                else:
                    files_payload.append((field, (filename, fobj)))
            # Prepare form fields (if any) - placeholders replaced
            form_payload = {}
            if "form" in step and isinstance(step["form"], dict):
                form_payload = replace_placeholders(step["form"], self.user_context)

            # If there's a JSON payload as well, we can include it as a form field named 'json' (optional)
            # But by default we treat req_payload as form fields merged (if it's a dict)
            if req_payload is not None and isinstance(req_payload, dict):
                # Merge JSON payload into form fields; careful with key collisions
                for k, v in req_payload.items():
                    if k not in form_payload:
                        form_payload[k] = v
                    else:
                        # collision: keep form field, but add a namespaced version
                        form_payload[f"json_{k}"] = v

            send_kwargs["files"] = files_payload
            send_kwargs["data"] = form_payload

            response = self.client.request(method.upper(), endpoint_with_values, **send_kwargs)

        else:
            # No files: keep existing behavior - send JSON if present, otherwise send form (if any)
            if "form" in step and step["form"]:
                # send regular form-data without files (application/x-www-form-urlencoded)
                data_payload = replace_placeholders(step["form"], self.user_context)
                response = self.client.request(
                    method.upper(),
                    endpoint_with_values,
                    headers=req_headers,
                    params=req_params,
                    data=data_payload
                )
            elif req_payload is not None:
                response = self.client.request(
                    method.upper(),
                    endpoint_with_values,
                    headers=req_headers,
                    params=req_params,
                    json=req_payload
                )
            else:
                # no payload: simple request
                response = self.client.request(
                    method.upper(),
                    endpoint_with_values,
                    headers=req_headers,
                    params=req_params
                )

        # Print response if requested
        if step.get("print_response"):
            print(f"\n[RESPONSE] {method} {endpoint_with_values}")
            print(f"Status: {response.status_code}")
            try:
                print(json.dumps(response.json(), indent=2))
            except Exception:
                # print up to first 300 chars of text body to keep logs readable
                print(response.text[:300])

        if not response.ok:
            print(f"[❌ ERROR] {method} {endpoint_with_values} -> {response.status_code}")
        else:
            print(f"[✅ OK] {method} {endpoint_with_values} -> {response.status_code}")

        # Extraction
        if "extract" in step:
            for ex in step["extract"]:
                source = ex.get("from")
                field = ex.get("field")
                save_as = ex.get("save_as")
                value = None
                if source == "json":
                    try:
                        value = deep_get(response.json(), field)
                    except Exception:
                        pass
                elif source == "headers":
                    value = response.headers.get(field)
                if value:
                    self.user_context[save_as] = value
                    print(f"[EXTRACTED] {save_as} = {value}")

    finally:
        # Close any opened file objects to prevent FD leaks
        for f in file_objs:
            try:
                f.close()
            except Exception:
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
                reader = csv.DictReader(f)
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
                    reader = csv.DictReader(f)
                    rows = [row for row in reader]
                    task_csv_cache[csv_task_file] = rows
                    print(f"📂 Preloaded task CSV: {csv_task_file} ({len(rows)} rows)")
            except Exception as e:
                print(f"⚠️ Could not preload {csv_task_file}: {e}")

        # 🔹 Added for subtask CSV support
        for sub in task_cfg.get("subtasks", []):
            sub_csv_file = sub.get("CSV_file")
            if sub_csv_file and os.path.exists(sub_csv_file) and sub_csv_file not in task_csv_cache:
                try:
                    with open(sub_csv_file, newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        rows = [row for row in reader]
                        task_csv_cache[sub_csv_file] = rows
                        print(f"📂 Preloaded subtask CSV: {sub_csv_file} ({len(rows)} rows)")
                except Exception as e:
                    print(f"⚠️ Could not preload {sub_csv_file}: {e}")

# ------------------------------
# Preload payload CSVs (for payload_from_csv)
# ------------------------------
payload_csv_cache = {}

for user in config.get("users", []):
    for task_cfg in user.get("tasks", []):
        # Task-level payload_from_csv
        if "payload_from_csv" in task_cfg:
            csv_info = task_cfg["payload_from_csv"]
            filepath = csv_info if isinstance(csv_info, str) else csv_info.get("file")
            if filepath and os.path.exists(filepath):
                try:
                    with open(filepath, newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        payload_csv_cache[filepath] = [row for row in reader]
                        print(f"📂 Preloaded payload CSV (task): {filepath} ({len(payload_csv_cache[filepath])} rows)")
                except Exception as e:
                    print(f"⚠️ Could not preload payload CSV {filepath}: {e}")

        # Subtask-level payload_from_csv
        for sub in task_cfg.get("subtasks", []):
            if "payload_from_csv" in sub:
                csv_info = sub["payload_from_csv"]
                filepath = csv_info if isinstance(csv_info, str) else csv_info.get("file")
                if filepath and os.path.exists(filepath):
                    try:
                        with open(filepath, newline="", encoding="utf-8") as f:
                            reader = csv.DictReader(f)
                            payload_csv_cache[filepath] = [row for row in reader]
                            print(f"📂 Preloaded payload CSV (subtask): {filepath} ({len(payload_csv_cache[filepath])} rows)")
                    except Exception as e:
                        print(f"⚠️ Could not preload payload CSV {filepath}: {e}")

# ------------------------------
# Load full JSON payload from preloaded CSV
# ------------------------------
def load_payload_from_csv_cache(filepath, column_name="payload"):
    if filepath not in payload_csv_cache:
        print(f"⚠️ Payload CSV not preloaded: {filepath}")
        return None

    rows = payload_csv_cache[filepath]
    if not rows:
        return None

    selected = random.choice(rows)
    json_data = selected.get(column_name)

    if not json_data:
        print(f"⚠️ Column '{column_name}' missing in payload CSV {filepath}")
        return None

    try:
        return json.loads(json_data)
    except Exception as e:
        print(f"⚠️ Invalid JSON in payload CSV {filepath}: {e}")
        return None


# ------------------------------
# Task factory
# ------------------------------
def make_task(task_config):
    @task
    def _t(self):
        if not hasattr(self, "user_context"):
            self.user_context = {}

        csv_task_file = task_config.get("CSV_file")

        # 1️⃣ Task-specific CSV (preloaded)
        if csv_task_file and csv_task_file in task_csv_cache:
            rows = task_csv_cache[csv_task_file]
            if rows:
                row = random.choice(rows)
                for k, v in row.items():
                    self.user_context[k] = apply_transforms(v, transform_rules)
                print(f"[CSV TASK] Picked row from {csv_task_file}: {row}")

        # 2️⃣ Global CSV fallback (combined)
        elif use_csv and csv_data:
            if csv_mode == "random":
                row = random.choice(csv_data)
            else:
                row = next(csv_cycle)
            for col in csv_columns:
                if col in row:
                    self.user_context[col] = apply_transforms(row[col], transform_rules)

        # 3️⃣ Execute task or subtasks
        if "subtasks" in task_config:
            print(f"\n▶ Executing combined task: {task_config.get('name', 'Unnamed Task')}")
            for sub in task_config["subtasks"]:
                # 🔹 Added CSV handling for each subtask
                sub_csv_file = sub.get("CSV_file")
                if sub_csv_file and sub_csv_file in task_csv_cache:
                    rows = task_csv_cache[sub_csv_file]
                    if rows:
                        row = random.choice(rows)
                        for k, v in row.items():
                            self.user_context[k] = apply_transforms(v, transform_rules)
                        print(f"[CSV SUBTASK] Picked row from {sub_csv_file}: {row}")

                execute_request(self, sub)
        else:
            execute_request(self, task_config)

    return _t

# ------------------------------
# Build Users from YAML
# ------------------------------
for user in config["users"]:
    wait_min, wait_max = user["wait_time"]

    if user.get("sequential", False):
        task_list = [make_task(t) for t in user["tasks"] for _ in range(t.get("weight", 1))]

        class SeqFlow(SequentialTaskSet):
            tasks = task_list
            def on_stop(self):
                raise StopUser()

        globals()[f"{user['name'].capitalize()}User"] = type(
            f"{user['name'].capitalize()}User",
            (HttpUser,),
            {
                "tasks": [SeqFlow],
                "wait_time": between(wait_min, wait_max),
                "weight": user["weight"],
                "host": global_host,
            },
        )
    else:
        task_funcs = [make_task(t) for t in user["tasks"] for _ in range(t.get("weight", 1))]
        globals()[f"{user['name'].capitalize()}User"] = type(
            f"{user['name'].capitalize()}User",
            (HttpUser,),
            {
                "tasks": task_funcs,
                "wait_time": between(wait_min, wait_max),
                "weight": user["weight"],
                "host": global_host,
            },
        )
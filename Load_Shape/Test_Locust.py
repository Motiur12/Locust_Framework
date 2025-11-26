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
# Execute a single HTTP step
# ------------------------------
def execute_request(self, step):
    method = step["method"]
    endpoint = step["endpoint"]

    req_headers = replace_placeholders(step.get("headers", {}), self.user_context)
    req_params = replace_placeholders(step.get("params", {}), self.user_context)
    req_payload = None

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

    endpoint_with_values = replace_placeholders(endpoint, self.user_context)

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
                print(f"[REQUEST] {method.upper()} {endpoint_with_values}")
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

            response = self.client.request(method.upper(), endpoint_with_values, **send_kwargs)

        else:
            if "form" in step and step["form"]:
                data_payload = replace_placeholders(step["form"], self.user_context)

                if step.get("print_request", False):
                    print("\n===== REQUEST DEBUG INFO =====")
                    print(f"[REQUEST] {method.upper()} {endpoint_with_values}")
                    print("Headers:")
                    print(json.dumps(req_headers, indent=2))
                    print("Query Params:")
                    print(json.dumps(req_params, indent=2))
                    print("Form Data:")
                    print(json.dumps(data_payload, indent=2))
                    print("===== END REQUEST INFO =====\n")

                response = self.client.request(
                    method.upper(),
                    endpoint_with_values,
                    headers=req_headers,
                    params=req_params,
                    data=data_payload
                )
            elif req_payload is not None:
                if step.get("print_request", False):
                    print("\n===== REQUEST DEBUG INFO =====")
                    print(f"[REQUEST] {method.upper()} {endpoint_with_values}")
                    print("Headers:")
                    print(json.dumps(req_headers, indent=2))
                    print("Query Params:")
                    print(json.dumps(req_params, indent=2))
                    print("JSON Payload:")
                    print(json.dumps(req_payload, indent=2))
                    print("===== END REQUEST INFO =====\n")

                response = self.client.request(
                    method.upper(),
                    endpoint_with_values,
                    headers=req_headers,
                    params=req_params,
                    json=req_payload
                )
            else:
                if step.get("print_request", False):
                    print("\n===== REQUEST DEBUG INFO =====")
                    print(f"[REQUEST] {method.upper()} {endpoint_with_values}")
                    print("Headers:")
                    print(json.dumps(req_headers, indent=2))
                    print("Query Params:")
                    print(json.dumps(req_params, indent=2))
                    print("(no body)")
                    print("===== END REQUEST INFO =====\n")

                response = self.client.request(
                    method.upper(),
                    endpoint_with_values,
                    headers=req_headers,
                    params=req_params
                )

        if step.get("print_response"):
            print(f"\n[RESPONSE] {method} {endpoint_with_values}")
            print(f"Status: {response.status_code}")
            try:
                print(json.dumps(response.json(), indent=2))
            except:
                print(response.text[:300])

        if not response.ok:
            print(f"[❌ ERROR] {method} {endpoint_with_values} -> {response.status_code}")
        else:
            print(f"[✅ OK] {method} {endpoint_with_values} -> {response.status_code}")

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

                if value:
                    self.user_context[save_as] = value
                    print(f"[EXTRACTED] {save_as} = {value}")

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
                        reader = csv.DictReader(f)
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
                            reader = csv.DictReader(f)
                            payload_csv_cache[filepath] = [row for row in reader]
                            print(f"📂 Preloaded payload CSV (subtask): {filepath} ({len(payload_csv_cache[filepath])} rows)")
                    except Exception as e:
                        print(f"⚠️ Could not preload payload CSV {filepath}: {e}")

# ------------------------------
# Load payload from CSV cache (FIXED for JSON filename)
# ------------------------------
def load_payload_from_csv_cache(filepath, column_name="payload"):
    if filepath not in payload_csv_cache:
        print(f"⚠️ Payload CSV not preloaded: {filepath}")
        return None

    rows = [r for r in payload_csv_cache[filepath] if r.get(column_name)]
    if not rows:
        print(f"⚠️ No valid rows found in {filepath}")
        return None

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
def make_task(task_config):
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

        elif use_csv and csv_data:
            if csv_mode == "random":
                row = random.choice(csv_data)
            else:
                row = next(csv_cycle)
            for col in csv_columns:
                if col in row:
                    self.user_context[col] = apply_transforms(row[col], transform_rules)

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
        
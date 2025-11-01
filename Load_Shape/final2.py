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
csv_files = config.get("csv_file")
csv_mode = config.get("csv_mode", "random")
csv_columns = config.get("csv_column", [])
if isinstance(csv_columns, str):
    csv_columns = [csv_columns]

if isinstance(csv_files, str):
    csv_files = [csv_files]

# ------------------------------
# Load CSV(s)
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
                print(f"📂 Loaded CSV file: {fpath} ({len(rows)} rows)")
        except Exception as e:
            print(f"⚠️ Could not load {fpath}: {e}")

    if csv_mode == "sequential" and csv_data:
        csv_cycle = cycle(csv_data)
else:
    print("⚠️ CSV usage disabled or no file provided.")


# ------------------------------
# Transformation Rules (from YAML)
# ------------------------------
transform_rules = config.get("transform", {})

def apply_transforms(value, rules):
    """Apply YAML-defined transformations to CSV values."""
    if not isinstance(value, str):
        return value
    v = value
    if rules.get("trim", True):
        v = v.strip()
    if rules.get("replace_spaces_with"):
        v = v.replace(" ", rules["replace_spaces_with"])
    if rules.get("lowercase", False):
        v = v.lower()
    if rules.get("suffix"):
        v = v + rules["suffix"]
    return v


# ------------------------------
# Helper: Replace placeholders like {{Token}}
# ------------------------------
def replace_placeholders(item, context):
    """Recursively replace {{key}} placeholders with context values."""
    if isinstance(item, dict):
        return {k: replace_placeholders(v, context) for k, v in item.items()}
    elif isinstance(item, list):
        return [replace_placeholders(v, context) for v in item]
    elif isinstance(item, str):
        for key, value in context.items():
            item = item.replace(f"{{{{{key}}}}}", str(value))
        return item
    return item


# ------------------------------
# Helper: Deep JSON extractor
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
# Helper: Load payload from .txt/.json
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

    # Payload can come from file or inline
    if "payload_from_file" in step:
        req_payload = load_payload_from_file(step["payload_from_file"], self.user_context)
    elif "payload" in step:
        req_payload = replace_placeholders(step["payload"], self.user_context)

    # Build final endpoint string
    endpoint_with_values = replace_placeholders(endpoint, self.user_context)


    # If `params` exists, manually append to endpoint to prevent encoding of '+'
    if req_params:
        query_parts = []
        for k, v in req_params.items():
            query_parts.append(f"{k}={v}")
        joined = "&".join(query_parts)
        if "?" in endpoint_with_values:
            endpoint_with_values = f"{endpoint_with_values}{joined}"
        else:
            endpoint_with_values = f"{endpoint_with_values}?{joined}"
        req_params = None  # Avoid double encoding


    # Prepare request kwargs
    request_kwargs = {}
    if req_headers:
        request_kwargs["headers"] = req_headers
    if req_payload:
        request_kwargs["json"] = req_payload

    # Send request
    response = self.client.request(method.upper(), endpoint_with_values, **request_kwargs)

    if step.get("print_response"):
        print(f"\n[RESPONSE] {method} {endpoint_with_values}")
        print(f"Status: {response.status_code}")
        try:
            print(json.dumps(response.json(), indent=2))
        except Exception:
            print(response.text[:300])

    if not response.ok:
        print(f"[❌ ERROR] {method} {endpoint_with_values} -> {response.status_code}")
    else:
        print(f"[✅ OK] {method} {endpoint_with_values} -> {response.status_code}")

    # Extraction support
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



# ------------------------------
# Task factory (supports subtasks)
# ------------------------------
def make_task(task_config):
    @task
    def _t(self):
        if not hasattr(self, "user_context"):
            self.user_context = {}

        # Load CSV row into context
        if use_csv and csv_data:
            if csv_mode == "random":
                row = random.choice(csv_data)
            else:
                row = next(csv_cycle)
            for col in csv_columns:
                if col in row:
                    raw_value = row[col]
                    clean_value = (
                        str(raw_value)
                        .strip()
                        .replace('"', '')
                        .replace("'", '')
                        .replace('[', '')
                        .replace(']', '')
                    )
                    clean_value = apply_transforms(clean_value, transform_rules)
                    self.user_context[col] = clean_value

        # Execute tasks
        if "subtasks" in task_config:
            print(f"\n▶ Executing combined task: {task_config.get('name', 'Unnamed Task')}")
            for sub in task_config["subtasks"]:
                execute_request(self, sub)
        else:
            execute_request(self, task_config)

    return _t


# ------------------------------
# Build Users
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
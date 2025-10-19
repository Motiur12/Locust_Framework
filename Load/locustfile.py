import yaml
import csv
from locust import HttpUser, task, between, SequentialTaskSet
from locust.exception import StopUser
import re
import random
from itertools import cycle

# ------------------------------
# Load YAML configuration
# ------------------------------
with open("test1_config.yaml", "r") as f:
    config = yaml.safe_load(f)

global_host = config.get("host")
use_csv = config.get("use_csv", False)
csv_file = config.get("csv_file")
csv_mode = config.get("csv_mode", "random")
csv_columns = config.get("csv_column", [])  # can be a list for multiple columns
if isinstance(csv_columns, str):
    csv_columns = [csv_columns]

# ------------------------------
# Load CSV if configured
# ------------------------------
csv_data = []
csv_cycle = None
if use_csv and csv_file:
    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            csv_data.append(row)
    if csv_mode == "sequential":
        csv_cycle = cycle(csv_data)

# ------------------------------
# Helper: Replace placeholders
# ------------------------------
def replace_placeholders(item, context):
    if isinstance(item, dict):
        return {k: replace_placeholders(v, context) for k, v in item.items()}
    elif isinstance(item, list):
        return [replace_placeholders(v, context) for v in item]
    elif isinstance(item, str):
        for key, value in context.items():
            item = item.replace(f"{{{{{key}}}}}", str(value))
        return item
    return item

# -----------------------------------
# Helper: For nested JSON extraction
# -----------------------------------
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
# Task Factory
# ------------------------------
def make_task(method, endpoint, headers=None, params=None, payload=None, form_data=None, files=None, extract=None, print_response=False):
    @task
    def _t(self):
        if not hasattr(self, "user_context"):
            self.user_context = {}

        # ------------------------------
        # Inject CSV data if configured
        # ------------------------------
        if use_csv and csv_columns:
            if csv_mode == "random":
                row = random.choice(csv_data)
            else:  # sequential
                row = next(csv_cycle)
            for col in csv_columns:
                if col in row:
                    self.user_context[col] = row[col]

        # Replace placeholders
        req_headers = replace_placeholders(headers, self.user_context) if headers else None
        req_params = replace_placeholders(params, self.user_context) if params else None
        req_payload = replace_placeholders(payload, self.user_context) if payload else None
        req_form = replace_placeholders(form_data, self.user_context) if form_data else None
        req_files = replace_placeholders(files, self.user_context) if files else None

        request_kwargs = {}
        if req_headers:
            request_kwargs["headers"] = req_headers
        if req_params:
            request_kwargs["params"] = req_params
        if req_payload:
            request_kwargs["json"] = req_payload
        if req_form:
            request_kwargs["data"] = req_form
        if req_files:
            opened_files = {k: open(v, "rb") for k, v in req_files.items()}
            request_kwargs["files"] = opened_files

        response = self.client.request(method.upper(), endpoint, **request_kwargs)

        if req_files:
            for f in request_kwargs["files"].values():
                f.close()

        # ------------------------------
        # Print response
        # ------------------------------
        if print_response:
            print(f"\n[RESPONSE] {method} {endpoint}")
            print(f"Status code: {response.status_code}")
            print(f"Headers: {response.headers}")
            try:
                print(f"Body: {response.json()}")
            except Exception:
                print(f"Body: {response.text}")

        if not response.ok:
            print(f"[ERROR] {method} {endpoint} -> {response.status_code}")
        else:
            print(f"[OK] {method} {endpoint} -> {response.status_code}")

        # ------------------------------
        # Extract values if needed
        # ------------------------------
        if extract:
            for ex in extract:
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

    return _t

# ------------------------------
# Build Users
# ------------------------------
for user in config["users"]:
    wait_min, wait_max = user["wait_time"]

    if user.get("sequential", False):
        task_list = []
        for t in user["tasks"]:
            for _ in range(t["weight"]):
                task_list.append(
                    make_task(
                        t["method"],
                        t["endpoint"],
                        t.get("headers"),
                        t.get("params"),
                        t.get("payload"),
                        t.get("form_data"),
                        t.get("files"),
                        t.get("extract"),
                        t.get("print_response", False),
                    )
                )

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
        task_funcs = []
        for t in user["tasks"]:
            for _ in range(t["weight"]):
                task_funcs.append(
                    make_task(
                        t["method"],
                        t["endpoint"],
                        t.get("headers"),
                        t.get("params"),
                        t.get("payload"),
                        t.get("form_data"),
                        t.get("files"),
                        t.get("extract"),
                        t.get("print_response", False),
                    )
                )

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


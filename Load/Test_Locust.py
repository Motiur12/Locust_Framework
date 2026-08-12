import yaml
import csv
import json
import os
import random
import re
import logging
from itertools import cycle
from locust import HttpUser, task, between, SequentialTaskSet, LoadTestShape, events
from locust.exception import StopUser
from locust.runners import WorkerRunner
# threading/time are imported AFTER locust too, so their gevent-patched
# (cooperative) versions are used — this is what lets RateLimiter.acquire()
# block a single greenlet with a real sleep without stalling every other
# concurrent user.
import threading
import time
# "requests" must be imported AFTER locust — locust's gevent monkey-patching
# (for SSL, sockets, etc.) needs to happen first, or a raw `requests` import
# can trigger SSL recursion errors.
import requests

# ------------------------------
# Load YAML configuration
# ------------------------------
with open("OrderPlace.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# ------------------------------
# Logging setup
#
# Replaces the old print()-everywhere approach. Under real load (hundreds/
# thousands of concurrent greenlets), unconditional print() + json.dumps on
# every single request is expensive and floods stdout, which both skews
# results and makes logs unusable. Using the logging module gives us:
#   - a level filter (skip building/formatting messages that won't be shown)
#   - optional file output separate from Locust's own console output
#   - a single place to control verbosity instead of scattered print()s
#
# Config (both optional, top-level in the YAML):
#   log_level: "INFO"       # DEBUG | INFO | WARNING | ERROR | CRITICAL (default INFO)
#   log_file: "engine.log"  # if set, also writes to this file (in addition
#                           # to propagating to Locust's own console handler)
#
# Level guide used throughout this file:
#   DEBUG    - per-request/response dumps (print_request/print_response),
#              successful ("OK") requests, CSV row picks, extract successes
#   INFO     - setup/lifecycle events (CSVs loaded, shape registered, a
#              sequential user finishing via run_once, etc.)
#   WARNING  - recoverable per-request problems (missing file, failed
#              extract, a request being skipped, config that's technically
#              valid but likely a mistake)
#   ERROR    - failed HTTP requests (non-2xx/3xx)
# Config-loading problems that make the whole run unsafe to start still
# raise ValueError immediately, rather than just being logged.
# ------------------------------
logger = logging.getLogger("locust_yaml_engine")

_log_level_name = str(config.get("log_level", "INFO")).upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
logger.setLevel(_log_level)

# If nothing has configured the root logger yet (e.g. running this module
# directly rather than via `locust`, which normally sets up its own
# handlers before importing the locustfile), fall back to a sane console
# format so messages aren't silently dropped.
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

_log_file = config.get("log_file")
if _log_file:
    file_handler = logging.FileHandler(_log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)
    logger.info(f"📝 Also logging to file: {_log_file}")

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

if not config.get("users"):
    raise ValueError(
        "config has no 'users:' section (or it's empty) — at least one user "
        "class with at least one task is required to build a locustfile."
    )

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
    logger.info(f"📈 Loaded custom load shape: {len(shape_config['stages'])} stage(s), "
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
#
# PERF: strings with no "{{" are returned untouched without ever looping
# over user_context — this matters a lot in practice, since most string
# fields (static headers, fixed URL path segments, literal payload values)
# never contain a placeholder, and this function runs on every header,
# param, payload, endpoint, and host for every single request.
# ------------------------------
def replace_placeholders(item, context):
    if isinstance(item, dict):
        return {k: replace_placeholders(v, context) for k, v in item.items()}
    elif isinstance(item, list):
        return [replace_placeholders(v, context) for v in item]
    elif isinstance(item, str):
        if "{{" not in item:
            return item
        for key, val in context.items():
            item = item.replace(f"{{{{{key}}}}}", str(val))
        return item
    return item

# ------------------------------
# Deep JSON extraction
#
# PERF: the common case is a flat field name with no "." or "[" — skip the
# regex split entirely for that case, since this runs once per "extract"
# entry on every request.
# ------------------------------
def deep_get(dictionary, path, default=None):
    if not path:
        return default
    if "." not in path and "[" not in path:
        return dictionary.get(path, default) if isinstance(dictionary, dict) else default

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
        logger.warning(f"⚠️ Payload file not found: {filepath}")
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read().strip()
        raw = replace_placeholders(raw, context)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"⚠️ Invalid JSON format in file: {filepath}")
            return None

# ------------------------------
# Returns the flat list of step dicts (HTTP-request-level configs) a task
# could possibly fire, regardless of whether it's a single-step task, a
# chained "subtasks" task, or a "branches" task (see conditional/branching
# flow below) — used anywhere we need to look at every reachable step
# without caring which shape produced it (CSV preload discovery, host
# validation, extract-key collection, etc).
# ------------------------------
def get_task_steps(task_cfg):
    if "branches" in task_cfg:
        steps = []
        for br in task_cfg.get("branches", []) or []:
            steps.extend(br.get("subtasks", []) or [])
        return steps
    if "subtasks" in task_cfg:
        return task_cfg["subtasks"]
    return [task_cfg]


def _step_has_host(step):
    """True if a step declares its own 'host:' override. Used by the
    multi-host validation pass below to check whether EVERY reachable step
    of a hostless user supplies its own host."""
    return bool(step.get("host"))


# ------------------------------
# Collect all "save_as" keys a task (across subtasks/branches) can write,
# so we can reset them before each run and avoid stale values
# leaking into a later step if an earlier step fails or a different
# branch runs than last time.
# ------------------------------
def collect_extract_keys(task_config):
    keys = set()
    for ex in task_config.get("extract", []) or []:
        if ex.get("save_as"):
            keys.add(ex["save_as"])
    for step in get_task_steps(task_config):
        for ex in step.get("extract", []) or []:
            if ex.get("save_as"):
                keys.add(ex["save_as"])
    return keys


# ------------------------------
# Conditional / branching flow
#
# A structured (non-eval) condition DSL usable in two places:
#   - a step-level "if:" (on a task-without-subtasks, or on any subtask)
#     to skip just that one step when the condition is false
#   - a task-level "branches:" (instead of "subtasks:") to pick exactly
#     one subtask chain to run, based on the first matching branch's "if"
#
# Conditions read from self.user_context — the same dict populated by CSV
# columns and prior "extract" results, so branching naturally chains off
# data already pulled from an earlier response (e.g. branch on the
# payment_status a previous step extracted).
# ------------------------------
CONDITION_OPS = {
    "equals", "not_equals", "exists", "not_exists",
    "contains", "not_contains", "gt", "lt", "gte", "lte", "in", "not_in",
}


def validate_condition(cond, path="if"):
    """Validates an "if:" condition at load time. Raises ValueError with a
    clear, path-qualified message on any structural problem, instead of
    letting a bad condition silently evaluate to False (or crash) mid-test."""
    if not isinstance(cond, dict):
        raise ValueError(f"{path} must be a mapping (dict), got {type(cond).__name__}.")

    if "all" in cond:
        if not isinstance(cond["all"], list) or not cond["all"]:
            raise ValueError(f"{path}.all must be a non-empty list of conditions.")
        for i, sub in enumerate(cond["all"]):
            validate_condition(sub, f"{path}.all[{i}]")
        return
    if "any" in cond:
        if not isinstance(cond["any"], list) or not cond["any"]:
            raise ValueError(f"{path}.any must be a non-empty list of conditions.")
        for i, sub in enumerate(cond["any"]):
            validate_condition(sub, f"{path}.any[{i}]")
        return
    if "not" in cond:
        validate_condition(cond["not"], f"{path}.not")
        return

    # Leaf condition
    if "var" not in cond:
        raise ValueError(f"{path} must have a 'var' field (or be an all/any/not combinator).")
    op = cond.get("op", "equals")
    if op not in CONDITION_OPS:
        raise ValueError(f"{path}.op '{op}' is not supported. Valid ops: {sorted(CONDITION_OPS)}")
    if op not in ("exists", "not_exists") and "value" not in cond:
        raise ValueError(f"{path}.op '{op}' requires a 'value' field.")
    if op in ("in", "not_in") and not isinstance(cond.get("value"), list):
        raise ValueError(f"{path}.op '{op}' requires 'value' to be a list.")


def evaluate_condition(cond, context):
    """Evaluates a validated "if:" condition against user_context at
    runtime. A comparison against a variable that was never set (e.g. an
    earlier extract didn't run or failed) evaluates to False rather than
    raising — this keeps branch logic predictable instead of crashing
    mid-test on a missing value."""
    if "all" in cond:
        return all(evaluate_condition(c, context) for c in cond["all"])
    if "any" in cond:
        return any(evaluate_condition(c, context) for c in cond["any"])
    if "not" in cond:
        return not evaluate_condition(cond["not"], context)

    var_name = cond["var"]
    op = cond.get("op", "equals")
    present = var_name in context
    actual = context.get(var_name)
    expected = cond.get("value")

    if op == "exists":
        return present
    if op == "not_exists":
        return not present
    if not present:
        return False

    if op == "equals":
        return str(actual) == str(expected)
    if op == "not_equals":
        return str(actual) != str(expected)
    if op == "contains":
        try:
            return expected in actual
        except TypeError:
            return False
    if op == "not_contains":
        try:
            return expected not in actual
        except TypeError:
            return True
    if op == "in":
        return any(str(actual) == str(v) for v in expected)
    if op == "not_in":
        return not any(str(actual) == str(v) for v in expected)
    if op in ("gt", "lt", "gte", "lte"):
        try:
            a, b = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        if op == "gt":
            return a > b
        if op == "lt":
            return a < b
        if op == "gte":
            return a >= b
        if op == "lte":
            return a <= b

    return False


def validate_task_conditions(task_cfg, label):
    """Validates the "if:"/"branches:" structure of a single task at load
    time — see module docstring above for the two mechanisms."""
    if "if" in task_cfg:
        validate_condition(task_cfg["if"], f"{label}.if")

    has_subtasks = "subtasks" in task_cfg
    has_branches = "branches" in task_cfg
    if has_subtasks and has_branches:
        raise ValueError(f"{label} cannot have both 'subtasks' and 'branches' — choose one.")

    if has_branches:
        branches = task_cfg["branches"]
        if not isinstance(branches, list) or not branches:
            raise ValueError(f"{label}.branches must be a non-empty list.")
        default_count = 0
        default_index = None
        for i, br in enumerate(branches):
            if not isinstance(br, dict) or "subtasks" not in br:
                raise ValueError(f"{label}.branches[{i}] must be a dict with a 'subtasks' list.")
            if not isinstance(br["subtasks"], list) or not br["subtasks"]:
                raise ValueError(f"{label}.branches[{i}].subtasks must be a non-empty list.")
            if "if" in br:
                validate_condition(br["if"], f"{label}.branches[{i}].if")
            else:
                default_count += 1
                default_index = i
            for j, sub in enumerate(br["subtasks"]):
                if "if" in sub:
                    validate_condition(sub["if"], f"{label}.branches[{i}].subtasks[{j}].if")
        if default_count > 1:
            raise ValueError(
                f"{label}.branches has {default_count} branches with no 'if' — "
                f"only one default (else) branch is allowed."
            )
        if default_count == 1 and default_index != len(branches) - 1:
            logger.warning(
                f"⚠️ {label}.branches has a default (no 'if') branch that isn't last "
                f"— branches are evaluated in order, so any branches after it will "
                f"never be reached. Move the default branch to the end."
            )
    elif has_subtasks:
        for j, sub in enumerate(task_cfg["subtasks"]):
            if "if" in sub:
                validate_condition(sub["if"], f"{label}.subtasks[{j}].if")


# ------------------------------
# Rate limiting per task/step
#
# Optional "rate_limit:" on a TASK (a whole task-without-subtasks, OR the
# overall pace of a "subtasks"/"branches" task as a unit) or on any
# individual STEP (a subtask, or a step inside a branch) caps how often
# that thing can fire, GLOBALLY across every concurrent user — not per
# user. e.g. rate_limit: 10 means "at most 10/sec total, no matter how
# many users are configured to hit it."
#
# Shorthand: rate_limit: 10                      (10 requests/sec)
# Full form: rate_limit: {rate: 10, per: "second"}   (second|minute|hour)
# Sharing:   rate_limit: {rate: 10, per: "second", name: "payment_gateway"}
#            Any other step/task that uses the SAME "name" shares ONE
#            limiter with this one — their combined call rate (not each
#            individually) is capped at 10/sec. Without "name", each step/
#            task gets its own independent limiter.
#
# Implementation: a simple constant-interval limiter (not a bursty token
# bucket) — calls are spaced out to arrive no faster than 1/rate seconds
# apart, enforced via a shared lock across all greenlets using that
# limiter. Uses the gevent-patched threading/time (imported after locust
# at the top of this file), so acquiring blocks only the calling
# greenlet/user, not the whole process.
#
# CAVEAT: the limiter lives in-process. In a single (standalone) `locust`
# run this IS a true global cap across every user. In distributed mode
# (--master/--worker), each WORKER process has its own independent
# limiter, so the actual combined rate across the whole run is
# (configured rate × number of workers) — divide the desired total
# accordingly for distributed runs.
# ------------------------------
class RateLimiter:
    def __init__(self, rate_per_sec):
        self.min_interval = (1.0 / rate_per_sec) if rate_per_sec > 0 else 0
        self._lock = threading.Lock()
        self._next_allowed = time.monotonic()

    def acquire(self):
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if self._next_allowed <= now:
                self._next_allowed = now + self.min_interval
                wait = 0
            else:
                wait = self._next_allowed - now
                self._next_allowed += self.min_interval
        if wait > 0:
            logger.debug(f"⏳ Rate limit: waiting {wait:.3f}s")
            time.sleep(wait)


_rate_limiters = {}
_rate_limiters_lock = threading.Lock()
_PER_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600}


def _normalize_rate_limit(rl_cfg):
    """Accepts either the shorthand number or the {rate, per, name} dict
    and returns (rate_per_sec, name_or_None)."""
    if isinstance(rl_cfg, (int, float)):
        return float(rl_cfg), None
    rate = float(rl_cfg["rate"])
    per = rl_cfg.get("per", "second")
    rate_per_sec = rate / _PER_UNIT_SECONDS[per]
    return rate_per_sec, rl_cfg.get("name")


def get_rate_limiter(rl_cfg, fallback_identity):
    """Resolves (creating if needed) the shared RateLimiter for a step/task.
    Steps/tasks with the same "name" share one limiter; without a "name",
    fallback_identity (typically id(step)) keeps each one independent."""
    rate_per_sec, name = _normalize_rate_limit(rl_cfg)
    key = name if name else fallback_identity
    with _rate_limiters_lock:
        limiter = _rate_limiters.get(key)
        if limiter is None:
            limiter = RateLimiter(rate_per_sec)
            _rate_limiters[key] = limiter
        elif name and limiter.min_interval != ((1.0 / rate_per_sec) if rate_per_sec > 0 else 0):
            logger.warning(
                f"⚠️ rate_limit name '{name}' was already registered with a different "
                f"rate — the FIRST rate this name was seen with is what's actually "
                f"enforced (this call's rate is ignored). Make every step/task sharing "
                f"this name use the same rate to avoid confusion."
            )
        return limiter


def validate_rate_limit(rl_cfg, path):
    if rl_cfg is None:
        return
    if isinstance(rl_cfg, (int, float)):
        if rl_cfg <= 0:
            raise ValueError(
                f"{path} must be a positive number (requests/sec) or a "
                f"mapping with 'rate' (and optional 'per'/'name')."
            )
        return
    if not isinstance(rl_cfg, dict):
        raise ValueError(
            f"{path} must be a number or a mapping with 'rate' (and optional 'per'/'name')."
        )
    rate = rl_cfg.get("rate")
    if rate is None or not isinstance(rate, (int, float)) or rate <= 0:
        raise ValueError(f"{path}.rate must be a positive number.")
    per = rl_cfg.get("per", "second")
    if per not in _PER_UNIT_SECONDS:
        raise ValueError(
            f"{path}.per must be one of {sorted(_PER_UNIT_SECONDS)} (got '{per}')."
        )
    name = rl_cfg.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError(f"{path}.name must be a string.")


for _user in config.get("users", []):
    for _i, _t in enumerate(_user.get("tasks", []) or []):
        _label = f"user '{_user.get('name', '?')}'.tasks[{_i}]"
        validate_task_conditions(_t, _label)
        validate_rate_limit(_t.get("rate_limit"), f"{_label}.rate_limit")
        for _j, _s in enumerate(get_task_steps(_t)):
            validate_rate_limit(_s.get("rate_limit"), f"{_label} step[{_j}].rate_limit")


# ------------------------------
# Build (and log, if enabled) a single debug dump for an outgoing request.
# Replaces four near-identical blocks of ~10 print() calls each. Guarded by
# logger.isEnabledFor(DEBUG) so the json.dumps() formatting work is skipped
# entirely when debug logging isn't on, even if a step sets print_request:
# true — the two controls combine (see logging setup notes near the top).
# ------------------------------
def _log_request_debug(method, url, headers, params, payload=None, form_data=None, files_meta=None):
    if not logger.isEnabledFor(logging.DEBUG):
        return
    lines = [
        "\n===== REQUEST DEBUG INFO =====",
        f"[REQUEST] {method.upper()} {url}",
        "Headers:", json.dumps(headers, indent=2),
        "Query Params:", json.dumps(params, indent=2),
    ]
    if payload is not None:
        lines.append("JSON Payload:")
        try:
            lines.append(json.dumps(payload, indent=2))
        except TypeError:
            lines.append(str(payload))
    if form_data is not None:
        lines.append("Form Data:")
        lines.append(json.dumps(form_data, indent=2))
    if files_meta is not None:
        lines.append("Files:")
        for field, filename, mime in files_meta:
            lines.append(f"  - field: {field}, filename: {filename}, mime: {mime or 'N/A'}")
    if payload is None and form_data is None and files_meta is None:
        lines.append("(no body)")
    lines.append("===== END REQUEST INFO =====\n")
    logger.debug("\n".join(lines))


# ------------------------------
# Execute a single HTTP step
# Returns True if the step is considered successful (response.ok and,
# if an extract was declared, the value was actually found), False otherwise.
# ------------------------------
def execute_request(self, step):
    # Optional per-step rate limit — blocks THIS greenlet (cooperatively,
    # via gevent-patched time.sleep) until the shared limiter for this
    # step says it's allowed to proceed. See RATE LIMITING section below
    # for how the limiter is resolved/shared and get_rate_limiter()'s
    # docstring for the "name:" sharing behavior.
    rate_limit_cfg = step.get("rate_limit")
    if rate_limit_cfg is not None:
        get_rate_limiter(rate_limit_cfg, id(step)).acquire()

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

        json_file_name = load_payload_from_csv_cache(filepath, self.user_context, column_name)
        if json_file_name:
            req_payload = json_file_name
    elif "payload" in step:
        req_payload = replace_placeholders(step["payload"], self.user_context)

    if payload_required and req_payload is None:
        logger.warning(f"⛔ SKIPPING request {step.get('method')} {step.get('endpoint')} — "
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
                    logger.warning(f"⚠️ File not found: {path} (field: {field})")
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
                files_meta = [
                    (field, meta[0], meta[2] if len(meta) >= 3 else None)
                    for field, meta in send_kwargs["files"]
                ]
                _log_request_debug(
                    method, request_url, req_headers, req_params,
                    payload=req_payload, form_data=send_kwargs["data"], files_meta=files_meta,
                )

            response = self.client.request(method.upper(), request_url, name=request_name, **send_kwargs)

        else:
            if "form" in step and step["form"]:
                data_payload = replace_placeholders(step["form"], self.user_context)

                if step.get("print_request", False):
                    _log_request_debug(method, request_url, req_headers, req_params, form_data=data_payload)

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
                    _log_request_debug(method, request_url, req_headers, req_params, payload=req_payload)

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
                    _log_request_debug(method, request_url, req_headers, req_params)

                response = self.client.request(
                    method.upper(),
                    request_url,
                    headers=req_headers,
                    params=req_params,
                    name=request_name
                )

        # PERF: parse the JSON body AT MOST ONCE per response, no matter how
        # many times it's needed below (print_response, and once per
        # "from: json" extract entry — a step with 3 such extracts used to
        # re-parse the same response body 3+ times). Cached lazily so a
        # step with only "from: headers" extracts never parses JSON at all.
        _json_cache = {"done": False, "value": None, "ok": False}

        def _cached_json():
            if not _json_cache["done"]:
                try:
                    _json_cache["value"] = response.json()
                    _json_cache["ok"] = True
                except (ValueError, TypeError):
                    _json_cache["value"] = None
                    _json_cache["ok"] = False
                _json_cache["done"] = True
            return _json_cache["value"], _json_cache["ok"]

        if step.get("print_response") and logger.isEnabledFor(logging.DEBUG):
            parsed, parsed_ok = _cached_json()
            body_line = json.dumps(parsed, indent=2) if parsed_ok else response.text[:300]
            logger.debug(f"\n[RESPONSE] {method} {request_url}\nStatus: {response.status_code}\n{body_line}")

        step_ok = bool(response.ok)

        if not response.ok:
            logger.error(f"[❌ ERROR] {method} {request_url} -> {response.status_code}")
        else:
            logger.debug(f"[✅ OK] {method} {request_url} -> {response.status_code}")

        if "extract" in step:
            for ex in step["extract"]:
                source = ex.get("from")
                field = ex.get("field")
                save_as = ex.get("save_as")
                value = None

                if source == "json":
                    parsed, parsed_ok = _cached_json()
                    if parsed_ok:
                        value = deep_get(parsed, field)
                elif source == "headers":
                    value = response.headers.get(field)

                if value is not None and value != "":
                    self.user_context[save_as] = value
                    logger.debug(f"[EXTRACTED] {save_as} = {value}")
                else:
                    # Extraction failed: make sure no stale value from a
                    # previous iteration lingers in context, and mark this
                    # step as unsuccessful so dependent subtasks can be skipped.
                    self.user_context.pop(save_as, None)
                    logger.warning(f"⚠️ [EXTRACT FAILED] Could not extract '{save_as}' "
                                   f"(from={source}, field={field}) — value not found.")
                    step_ok = False

        return step_ok

    finally:
        for f in file_objs:
            try:
                f.close()
            except Exception:
                pass

# ------------------------------
# Setup / Teardown hooks (run ONCE for the whole test, not per user)
#
# "setup:" runs once before any users are spawned (Locust's test_start
# event) — e.g. log in once and extract a shared token, warm up a cache,
# or seed shared test data. Anything captured via "extract" here is copied
# into every user's own user_context when that user starts, so the rest of
# the run can reference it via "{{var}}" like any other extracted value.
#
# "teardown:" runs once after the test stops (Locust's test_stop event) —
# e.g. delete data created during the run, or notify a webhook. Teardown
# always runs best-effort: a failing step is logged and the NEXT teardown
# step still runs.
#
# Setup is different: a failing REQUIRED step (no continue_on_failure)
# aborts the whole run before any load is generated, since starting a load
# test against a service you couldn't even log into just produces noise.
#
# Both use the same step schema as a normal task/subtask step (method,
# endpoint, host, headers, payload, extract, if, etc.) by reusing
# execute_request() through a lightweight stand-in for a User — these run
# outside of any single user's lifecycle, driven by plain requests.Session
# rather than Locust's per-user HttpSession, so they intentionally do NOT
# appear in the load test's own request statistics.
# ------------------------------
global_context = {}


class _HookClient:
    """Minimal stand-in for HttpUser's self.client, just enough for
    execute_request() to work: resolves a relative endpoint against
    global_host (mirroring how a real user's client applies its own
    "host"), or uses the full URL as-is when execute_request already
    built one via a step-level "host" override."""

    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()

    def request(self, method, url, name=None, **kwargs):
        if url.startswith("http://") or url.startswith("https://"):
            full_url = url
        elif self.base_url:
            full_url = f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"
        else:
            full_url = url
        return self.session.request(method, full_url, **kwargs)


class _HookRunner:
    """Stand-in "self" passed to execute_request() for setup/teardown
    steps — has just the two attributes execute_request actually uses."""

    def __init__(self):
        self.client = _HookClient(global_host)
        self.user_context = global_context


def _run_hook_steps(steps, label, abort_on_failure):
    hook_self = _HookRunner()
    for i, step in enumerate(steps):
        step_if = step.get("if")
        if step_if is not None and not evaluate_condition(step_if, hook_self.user_context):
            logger.debug(f"⏭ Skipping {label} step {i} ({step.get('method')} {step.get('endpoint')}) "
                         f"— condition not met.")
            continue

        success = execute_request(hook_self, step)

        if not success:
            if abort_on_failure and not step.get("continue_on_failure", False):
                logger.error(f"❌ {label} step {i} ({step.get('method')} {step.get('endpoint')}) failed "
                             f"— aborting before load begins. Set continue_on_failure: true on this "
                             f"step if it's OK for the run to continue anyway.")
                return False
            else:
                logger.warning(f"⚠️ {label} step {i} ({step.get('method')} {step.get('endpoint')}) failed"
                               + ("" if abort_on_failure else " — continuing (teardown is best-effort)."))
    return True


def validate_hook_steps(steps, label):
    if steps is None:
        return
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"'{label}:' must be a non-empty list of steps.")
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or not step.get("method") or not step.get("endpoint"):
            raise ValueError(f"{label}[{i}] must be a dict with at least 'method' and 'endpoint'.")
        if "if" in step:
            validate_condition(step["if"], f"{label}[{i}].if")
        if "rate_limit" in step:
            validate_rate_limit(step["rate_limit"], f"{label}[{i}].rate_limit")


validate_hook_steps(config.get("setup"), "setup")
validate_hook_steps(config.get("teardown"), "teardown")


@events.test_start.add_listener
def _on_test_start(environment, **kwargs):
    # In distributed mode (--master/--worker), only the master should run
    # setup — workers would each try to run it again otherwise.
    if isinstance(environment.runner, WorkerRunner):
        return
    setup_steps = config.get("setup")
    if not setup_steps:
        return
    logger.info(f"🚀 Running {len(setup_steps)} setup step(s) before load begins...")
    ok = _run_hook_steps(setup_steps, "setup", abort_on_failure=True)
    if ok:
        logger.info("✅ Setup complete.")
    else:
        logger.error("❌ Setup failed — stopping the test before any users are spawned.")
        environment.runner.quit()


@events.test_stop.add_listener
def _on_test_stop(environment, **kwargs):
    if isinstance(environment.runner, WorkerRunner):
        return
    teardown_steps = config.get("teardown")
    if not teardown_steps:
        return
    logger.info(f"🧹 Running {len(teardown_steps)} teardown step(s)...")
    _run_hook_steps(teardown_steps, "teardown", abort_on_failure=False)
    logger.info("🧹 Teardown complete.")

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
                logger.info(f"📂 Loaded global CSV file: {fpath} ({len(rows)} rows)")
        except Exception as e:
            logger.warning(f"⚠️ Could not load {fpath}: {e}")
    if csv_mode == "sequential" and csv_data:
        csv_cycle = cycle(csv_data)
else:
    logger.info("⚠️ CSV usage disabled or no file provided.")

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
                    logger.info(f"📂 Preloaded task CSV: {csv_task_file} ({len(rows)} rows)")
            except Exception as e:
                logger.warning(f"⚠️ Could not preload {csv_task_file}: {e}")

        for sub in get_task_steps(task_cfg):
            sub_csv_file = sub.get("CSV_file")
            if sub_csv_file and os.path.exists(sub_csv_file) and sub_csv_file not in task_csv_cache:
                try:
                    with open(sub_csv_file, newline="", encoding="utf-8") as f:
                        reader = safe_dict_reader(f)
                        rows = [row for row in reader]
                        task_csv_cache[sub_csv_file] = rows
                        logger.info(f"📂 Preloaded subtask CSV: {sub_csv_file} ({len(rows)} rows)")
                except Exception as e:
                    logger.warning(f"⚠️ Could not preload {sub_csv_file}: {e}")

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
                        logger.info(f"📂 Preloaded payload CSV (task): {filepath} ({len(payload_csv_cache[filepath])} rows)")
                except Exception as e:
                    logger.warning(f"⚠️ Could not preload payload CSV {filepath}: {e}")

        for sub in get_task_steps(task_cfg):
            if "payload_from_csv" in sub:
                csv_info = sub["payload_from_csv"]
                filepath = csv_info if isinstance(csv_info, str) else csv_info.get("file")
                if filepath and os.path.exists(filepath):
                    try:
                        with open(filepath, newline="", encoding="utf-8") as f:
                            reader = safe_dict_reader(f)
                            payload_csv_cache[filepath] = [row for row in reader]
                            logger.info(f"📂 Preloaded payload CSV (subtask): {filepath} ({len(payload_csv_cache[filepath])} rows)")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not preload payload CSV {filepath}: {e}")

# ------------------------------
# Load payload from CSV cache
# Row selection now honors the global csv_mode ("sequential" vs "random"),
# same as the token CSV, instead of always being random.
#
# The docs promise "placeholders inside that JSON file are substituted" —
# so this delegates the actual file read to load_payload_from_file(),
# which substitutes on the RAW TEXT before parsing (same as a plain
# payload_from_file step gets). This also means placeholders can be used
# unquoted for non-string injection (e.g. "qty": {{quantity}}), exactly
# like payload_from_file already supports.
# ------------------------------
payload_csv_cycles = {}


def load_payload_from_csv_cache(filepath, context, column_name="payload"):
    if filepath not in payload_csv_cache:
        logger.warning(f"⚠️ Payload CSV not preloaded: {filepath}")
        return None

    rows = [r for r in payload_csv_cache[filepath] if r.get(column_name)]
    if not rows:
        logger.warning(f"⚠️ No valid rows found in {filepath}")
        return None

    if csv_mode == "sequential":
        cache_key = (filepath, column_name)
        if cache_key not in payload_csv_cycles:
            payload_csv_cycles[cache_key] = cycle(rows)
        selected = next(payload_csv_cycles[cache_key])
    else:
        selected = random.choice(rows)

    json_file_name = selected.get(column_name)
    if not json_file_name:
        logger.warning(f"⚠️ No filename found in column '{column_name}'.")
        return None

    return load_payload_from_file(json_file_name, context)

# ------------------------------
# Runs a chain of subtasks (used for both a plain "subtasks:" task and a
# selected branch's "subtasks:"). Each subtask may have its own "if:" —
# a false condition SKIPS that one subtask (not a failure, chain
# continues) rather than stopping the whole chain.
# ------------------------------
def _run_subtask_chain(self, subtasks, chain_label):
    for sub in subtasks:
        sub_if = sub.get("if")
        if sub_if is not None and not evaluate_condition(sub_if, self.user_context):
            logger.debug(f"⏭ Skipping subtask in '{chain_label}' — condition not met "
                         f"({sub.get('method')} {sub.get('endpoint')}).")
            continue

        sub_csv_file = sub.get("CSV_file")
        if sub_csv_file and sub_csv_file in task_csv_cache:
            rows = task_csv_cache[sub_csv_file]
            if rows:
                row = random.choice(rows)
                for k, v in row.items():
                    self.user_context[k] = apply_transforms(v, transform_rules)
                logger.debug(f"[CSV SUBTASK] Picked row from {sub_csv_file}: {row}")

        success = execute_request(self, sub)

        if not success and not sub.get("continue_on_failure", False):
            logger.warning(f"⛔ Stopping chain for task '{chain_label}' "
                           f"— subtask {sub.get('method')} {sub.get('endpoint')} failed "
                           f"(set continue_on_failure: true on the subtask to override).")
            break


# ------------------------------
# Task factory
# ------------------------------
def make_task(task_config, stop_after=False):
    task_name = task_config.get("name", "Unnamed Task")

    @task
    def _t(self):
        if not hasattr(self, "user_context"):
            # Seed with a COPY of anything "setup:" extracted, so every
            # user starts with e.g. a shared token without needing its own
            # login step. Copy, not reference — so per-user extracts don't
            # cross-contaminate other users.
            self.user_context = dict(global_context)

        csv_task_file = task_config.get("CSV_file")

        if csv_task_file and csv_task_file in task_csv_cache:
            rows = task_csv_cache[csv_task_file]
            if rows:
                row = random.choice(rows)
                for k, v in row.items():
                    self.user_context[k] = apply_transforms(v, transform_rules)
                logger.debug(f"[CSV TASK] Picked row from {csv_task_file}: {row}")

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

        # Reset any keys this task/subtasks/branches could produce via
        # "extract" so a failed step this iteration — or simply a different
        # branch running than last time — can't leak a stale value from a
        # previous iteration into a later step (e.g. a stale order_id).
        for key in collect_extract_keys(task_config):
            self.user_context.pop(key, None)

        # Task-level "if:" gates the WHOLE task (single-step, subtasks, or
        # branches alike) — false means this task's slot in the sequence
        # does nothing this iteration.
        task_if = task_config.get("if")
        if task_if is not None and not evaluate_condition(task_if, self.user_context):
            logger.debug(f"⏭ Skipping task '{task_name}' — condition not met.")

        elif "branches" in task_config:
            chosen = None
            for br in task_config["branches"]:
                cond = br.get("if")
                if cond is None or evaluate_condition(cond, self.user_context):
                    chosen = br
                    break
            if chosen is None:
                logger.debug(f"⏭ No branch matched for task '{task_name}' — skipping.")
            else:
                # Task-level rate_limit gates the whole chain as ONE unit
                # (e.g. "only 5 order flows/sec total", not "5 of each
                # subtask/sec") — only consumed once a branch actually
                # matched, so a skipped iteration doesn't eat into the
                # budget. (A single-step task's own "rate_limit" is instead
                # handled inside execute_request(), since there's no
                # separate chain to gate.)
                task_rate_limit = task_config.get("rate_limit")
                if task_rate_limit is not None:
                    get_rate_limiter(task_rate_limit, id(task_config)).acquire()
                logger.debug(f"\n▶ Executing branch of task: {task_name}")
                _run_subtask_chain(self, chosen["subtasks"], task_name)

        elif "subtasks" in task_config:
            task_rate_limit = task_config.get("rate_limit")
            if task_rate_limit is not None:
                get_rate_limiter(task_rate_limit, id(task_config)).acquire()
            logger.debug(f"\n▶ Executing combined task: {task_name}")
            _run_subtask_chain(self, task_config["subtasks"], task_name)

        else:
            execute_request(self, task_config)

        if stop_after:
            # NOTE: on_stop() on a SequentialTaskSet only fires on an
            # explicit interrupt/shutdown — it does NOT fire automatically
            # just because you reached the end of the task list (a
            # SequentialTaskSet loops back to the start forever otherwise).
            # Raising StopUser() here, right after the last task in the
            # sequence, is what actually makes "run_once" work — regardless
            # of whether this particular pass actually ran anything (its
            # "if" was false, or no branch matched).
            logger.info("🛑 run_once: sequence complete, stopping this user.")
            raise StopUser()

    return _t

# ------------------------------
# Build Users from YAML (Updated for weight)
# ------------------------------
for user in config.get("users", []):
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
        # every task/subtask/branch-subtask for this user supplies its own
        # step-level "host" (case C) — otherwise Locust would only fail
        # loudly at the first request, mid-test, so we check that here.
        all_steps_have_host = all(
            _step_has_host(s)
            for t in user.get("tasks", [])
            for s in get_task_steps(t)
        )

        if not all_steps_have_host:
            raise ValueError(
                f"User '{user['name']}' has no host set (no global 'host:', no "
                f"user-level 'host:'), and at least one of its tasks/subtasks "
                f"doesn't declare its own step-level 'host:' either. Set one of "
                f"these so requests have somewhere to go."
            )
        else:
            logger.info(f"ℹ️ User '{user['name']}' has no default host — relying entirely "
                  f"on step-level 'host:' overrides for all its requests.")

    # Flag (don't fail) a user-level host that's fully shadowed by
    # step-level overrides on every single task/branch — likely dead config.
    if user_host and user.get("host"):
        all_steps_override = all(
            _step_has_host(s)
            for t in user.get("tasks", [])
            for s in get_task_steps(t)
        )

        if all_steps_override:
            logger.warning(f"⚠️ User '{user['name']}' sets its own 'host:' ({user_host}), but "
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
                # Seed with a COPY of anything "setup:" extracted (see
                # global_context / _on_test_start) so every user starts
                # with e.g. a shared token without its own login step.
                self.user_context = dict(global_context)
                if csv_scope == "per_user" and use_csv and csv_data:
                    row = random.choice(csv_data) if csv_mode == "random" else next(csv_cycle)
                    for col in csv_columns:
                        if col in row:
                            self.user_context[col] = apply_transforms(row[col], transform_rules)
                    self.user_context["_csv_sticky"] = True
                    logger.debug(f"[CSV STICKY] Assigned once for this user: "
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
                logger.warning(f"⚠️ shape user_classes references '{n}' but no '{cls_name}' was built — skipping it.")
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

    logger.info(f"📈 Custom load shape 'YamlLoadShape' registered "
          f"({len(_stages)} stage(s), loop={_loop}, total_duration={_stages[-1]['duration']}s)")

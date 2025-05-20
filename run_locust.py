import sys
import subprocess
import logging
from helper.config_reader import load_config

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Load configuration from config.properties
config = load_config()

# Helper to safely parse integer config values with default and consistent error handling
def get_int_config(config, key, default):
    value = config.get(key, default)
    try:
        return int(value)
    except (ValueError, TypeError):
        logging.warning("Invalid '%s'. Defaulting to %s.", key, default)
        return default

# Helper to determine boolean config flags from various truthy values
def get_bool_config(config, key, default=False):
    truthy = {"true", "1", "yes", "on"}
    value = str(config.get(key, str(default))).strip().lower()
    return value in truthy

# Read and parse configurations
base_url = config.get("baseUrl", "http://localhost")
spawn_rate = get_int_config(config, "spawnRate", 1)
users = get_int_config(config, "users", 10)
run_time = config.get("runTime", "1m")
headless = get_bool_config(config, "headless", False)
locustfile = config.get("locustFile", "locustfile.py")  # Allow override via config

# Build the command for running Locust
command = [
    "locust",
    "-f", locustfile,
    "--host", base_url,
    "--users", str(users),
    "--spawn-rate", str(spawn_rate),
    "--run-time", run_time
]

if headless:
    command.append("--headless")

logging.info("Executing Locust with command: %s", ' '.join(command))

# Run Locust with error handling
try:
    subprocess.run(command, check=True)
except FileNotFoundError as e:
    logging.error("Executable not found: %s", e.filename)
    sys.exit(1)
except subprocess.CalledProcessError as e:
    logging.error("Locust execution failed with exit code %s", e.returncode)
    sys.exit(e.returncode)
except Exception as e:
    logging.error("Unexpected error running Locust: %s", str(e))
    sys.exit(1)


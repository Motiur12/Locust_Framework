import sys
import subprocess
from helper.config_reader import load_config

# Load configuration from config.properties
config = load_config()

# Fetch configuration values directly from the loaded config
base_url = config.get("baseUrl")
spawn_rate = int(config.get("spawnRate"))  # Default spawn rate if not specified
users = int(config.get("users"))  # Default to 10 users if not specified
run_time = config.get("runTime")  # Default to 1m runtime if not specified
headless = config.get("headless")

# Build the command for running Locust
command = [
    "locust", 
    "-f", "locustfile.py", 
    "--host", base_url,
    "--users", str(users),
    "--spawn-rate", str(spawn_rate),
    "--run-time", run_time
]

# Run Locust programmatically
if headless == "true":
    command.append("--headless")  # Run in headless mode if specified

# Print out the command being executed
print(f"Executing Locust with command: {' '.join(command)}")

# Execute the command using subprocess
subprocess.run(command)

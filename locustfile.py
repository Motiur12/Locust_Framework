from locust import HttpUser, task, between
from tests.demo_test import UserAPITest
from helper.config_reader import load_config

config = load_config()

# Fetch configuration values directly from the loaded config
base_url = config.get("baseUrl")
wait_time = int(config.get("waitTime", 1))
spawn_rate = int(config.get("spawnRate", 2))
users = int(config.get("users", 10))  # Default to 10 users
run_time = config.get("runTime", "1m")
headless = config.get("headless", "true").lower() == "true"

class UserAPITest(HttpUser):
    wait_time = between(wait_time, wait_time)
    host = base_url

    def on_start(self):
        """Setup logic for when a user starts (e.g., login)"""
        pass

    @task
    def get_user(self):
        self.test_api.test_get_user()  # This lives in test_user_api.py





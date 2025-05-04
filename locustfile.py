from locust import HttpUser, task, between
from tests.demo_test import UserAPITest
from helper.config_reader import load_config

config = load_config()
base_url = config.get("base_url")
min_wait = int(config.get("minWaitTime"))
max_wait = int(config.get("maxWaitTime"))

class LocustFile(HttpUser):
    wait_time = between(min_wait, max_wait)

    def on_start(self):
        """Setup logic for when a user starts (e.g., login)"""
        self.test_api = UserAPITest()

    @task
    def get_user(self):
        self.test_api.test_get_user()

import threading
from prometheus_client import start_http_server
from locust import HttpUser, task, between, events
from pages.list import ListPage
from helper.logging_setup import setup_file_logging
from prometheus.prometheusMetrics import *
from prometheus_helper.prometheus_active_users import start_active_users_updater
from prometheus_helper.prometheus_listeners import on_request, track_task_duration

setup_file_logging()

# 🔹 Start Prometheus server
def start_prometheus_server():
    start_http_server(8001)
    print("✅ Prometheus metrics at http://localhost:8001")

threading.Thread(target=start_prometheus_server, daemon=True).start()

# 🔹 Poll active users in background
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    start_active_users_updater(environment)

# 🔹 Request Listener
@events.request.add_listener
def request_listener(**kwargs):
    on_request(**kwargs)

# 🔹 Locust User
class DemoUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        print("🚀 Starting DemoUser")
        self.list_page = ListPage(self.client, console_logging=True)

    @task
    @track_task_duration("get_list_of_users")
    def get_list_of_users(self):
        self.list_page.get_list_of_users()

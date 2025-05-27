import threading
from prometheus_client import start_http_server
from locust import HttpUser, task, between, events
from helper.logging_setup import setup_file_logging
from prometheus.prometheusMetrics import *
from prometheus_helper.prometheus_active_users import start_active_users_updater
from prometheus_helper.prometheus_listeners import on_request
from users.light_user import LightUser
from users.heavy_user import HeavyUser
from custom_load.stage_load_shape import AdvancedLoadShape
from reporter.TestReporter import TestReporter


reporter = None
setup_file_logging()

# 🔹 Start Prometheus server
def start_prometheus_server():
    start_http_server(8001)
    print("✅ Prometheus metrics at http://localhost:8001")

threading.Thread(target=start_prometheus_server, daemon=True).start()

# 🔹 Poll active users in background
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global reporter
    start_active_users_updater(environment)
    reporter = TestReporter(environment)

# 🔹 Request Listener
@events.request.add_listener
def request_listener(**kwargs):
    on_request(**kwargs)
    
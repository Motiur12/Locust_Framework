import threading
from locust import events
from prometheus_client import start_http_server
from helper.logging_setup import setup_file_logging
from prometheus.prometheusMetrics import *  # assuming you're defining custom Prometheus metrics here
from prometheus_helper.prometheus_active_users import start_active_users_updater
from prometheus_helper.prometheus_listeners import on_request
from users.light_user import LightUser
from users.heavy_user import HeavyUser
from custom_load.stage_load_shape import AdvancedLoadShape
from report.stageLoad import ConsoleReport

# 🔹 Initialize global reporter
console_reporter = ConsoleReport(AdvancedLoadShape.stages)

# 🔹 Setup logging
setup_file_logging()

# 🔹 Start Prometheus metrics server
def start_prometheus_server():
    start_http_server(8001)
    print("✅ Prometheus metrics at http://localhost:8001")

threading.Thread(target=start_prometheus_server, daemon=True).start()

# 🔹 Event: Test Start
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    start_active_users_updater(environment)
    console_reporter.on_test_start()

# 🔹 Event: Request
@events.request.add_listener
def request_listener(**kwargs):
    on_request(**kwargs)
    console_reporter.on_request(**kwargs)

# 🔹 Event: Test Stop
@events.test_stop.add_listener
def on_test_stop(**kwargs):
    console_reporter.on_test_stop(**kwargs)

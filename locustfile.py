from pages.list import ListPage
from helper.logging_setup import setup_file_logging

setup_file_logging()

from locust import HttpUser, task, between, events
from prometheus_client import start_http_server, Counter, Histogram
import time
import threading

# Define Prometheus metrics 
REQUEST_COUNT = Counter('locust_requests_total', 'Total number of HTTP requests', ['method', 'endpoint', 'status_code'])
REQUEST_LATENCY = Histogram('locust_request_latency_seconds', 'Request latency in seconds', ['endpoint'])

# Start Prometheus server on a background thread
def start_prometheus_server():
    start_http_server(8001)  # Prometheus will scrape from this port
    print("Prometheus metrics available at http://localhost:8001/")

threading.Thread(target=start_prometheus_server, daemon=True).start()

# Hook into request events
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, exception, start_time, url, **kwargs):
    endpoint = name or url
    status_code = str(response.status_code) if response else '500'
    REQUEST_COUNT.labels(method=request_type, endpoint=endpoint, status_code=status_code).inc()
    REQUEST_LATENCY.labels(endpoint=endpoint).observe(response_time / 1000)

class ReqresUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        print("==================Starting Test====================")
        self.list_page = ListPage(self.client, console_logging=True)

    @task
    def test_get_users_page_2(self):
        self.list_page.save_user_id_from_page_2()
        
    @task
    def test_get_users(self):
        self.list_page.get_list_of_users()

    @task
    def post_user(self):
        self.list_page.post_user()

    @task
    def get_list_of_users(self):
        self.list_page.get_list_of_users()
    
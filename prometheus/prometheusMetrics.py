from prometheus_client import Counter, Histogram, Summary, Gauge

# 🔹 Counters

# Total number of HTTP requests made, labeled by HTTP method, endpoint, and status code.
REQUEST_COUNT = Counter(
    'locust_requests_total', 
    'Total HTTP requests', 
    ['method', 'endpoint', 'status_code']
    )

# Total number of failed HTTP requests, labeled by method and endpoint.
REQUEST_FAILURES = Counter(
    'locust_requests_failed_total',
    'Total failed HTTP requests', 
    ['method', 'endpoint']
    )

# Total number of times a request was retried, labeled by endpoint.
REQUEST_RETRIES = Counter(
    'locust_request_retries_total', 
    'Total number of request retries', 
    ['endpoint']
    )

# Total number of request timeouts, labeled by endpoint.
TIMEOUTS = Counter(
    'locust_timeouts_total', 
    'Total request timeouts', 
    ['endpoint']
    )

# Total number of failed validations (e.g. business logic checks), labeled by endpoint and failure reason.
VALIDATION_FAILURES = Counter(
    'locust_validation_failures_total', 
    'Business logic validation failures', 
    ['endpoint', 'reason']
    )

# Total errors grouped by Python exception type and endpoint.
ERROR_TYPE_COUNT = Counter(
    'locust_error_type_total',
    'Total errors by type',
    ['error_type', 'endpoint']
    )

# 🔹 Histograms & Summaries

# Time taken for HTTP requests.
REQUEST_LATENCY = Histogram(
    'locust_request_latency_seconds', 
    'Request latency in seconds', 
    ['endpoint']
    )

# Request duration summary for percentiles.
REQUEST_DURATION_SUMMARY = Summary(
    'locust_request_duration_summary_seconds', 
    'Request duration summary in seconds',
    ['endpoint']
    )

# Size of the response body.
RESPONSE_SIZE = Histogram(
    'locust_response_size_bytes', 
    'Response size in bytes', 
    ['endpoint']
    )

# How long each Locust task takes.
TASK_DURATION = Histogram(
    'locust_task_duration_seconds', 
    'Task execution duration', 
    ['task_name']
    )

# Size of data sent in the request.
REQUEST_PAYLOAD_SIZE = Histogram(
    'locust_request_payload_bytes', 
    'Request payload size in bytes', 
    ['endpoint']
    )

# 🔹 Gauges

# Tracks the number of ongoing (incomplete) HTTP requests.
IN_PROGRESS = Gauge(
    'locust_requests_in_progress', 
    'Number of requests in progress'
    )

# Monitors how many users of each Locust user class are active.
ACTIVE_USERS = Gauge(
    'locust_active_users', 
    'Number of active Locust users',
    ['user_class']
    )

# Measures the current size of a custom queue you define.
QUEUE_SIZE = Gauge(
    'locust_custom_queue_size', 
    'Size of custom queue'
    )  # Optional, for custom logic

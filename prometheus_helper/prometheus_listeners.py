import time
from prometheus.prometheusMetrics import *

def on_request(request_type, name, response_time, response_length, response, context, exception, start_time, url, **kwargs):
    endpoint = name or url
    status_code = str(response.status_code) if response else '500'

    # Mark request in progress
    IN_PROGRESS.inc()
    try:
        REQUEST_COUNT.labels(method=request_type, endpoint=endpoint, status_code=status_code).inc()
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(response_time / 1000)
        REQUEST_DURATION_SUMMARY.labels(endpoint=endpoint).observe(response_time / 1000)
        if response_length:
            RESPONSE_SIZE.labels(endpoint=endpoint).observe(response_length)

        if exception or (response and not response.ok):
            REQUEST_FAILURES.labels(method=request_type, endpoint=endpoint).inc()

        if exception:
            error_type = type(exception).__name__
            ERROR_TYPE_COUNT.labels(error_type=error_type, endpoint=endpoint).inc()
            if "timeout" in error_type.lower():
                TIMEOUTS.labels(endpoint=endpoint).inc()

        if response and response.text and "error" in response.text:
            VALIDATION_FAILURES.labels(endpoint=endpoint, reason="error_in_response").inc()

        # logging.info(f"[DEBUG] Latency: {response_time / 1000:.3f}s for {endpoint} (status {status_code})")

    finally:
        IN_PROGRESS.dec()


def track_task_duration(task_name):
    def wrapper(func):
        def wrapped(*args, **kwargs):
            start = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.time() - start
                TASK_DURATION.labels(task_name=task_name).observe(duration)
        return wrapped
    return wrapper

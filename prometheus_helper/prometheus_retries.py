from functools import wraps
from prometheus.prometheusMetrics import REQUEST_RETRIES

def track_retries(endpoint, max_retries=3):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            retries = 0
            while retries <= max_retries:
                response = func(self, *args, **kwargs)
                if response.status_code < 500:
                    return response
                retries += 1
                REQUEST_RETRIES.labels(endpoint=endpoint).inc()
            return response
        return wrapper
    return decorator

# @task
# @track_task_duration("get_list_of_users")
# @track_retries(endpoint="/users", max_retries=2)
# def get_list_of_users(self):
#     return self.client.get("/users")
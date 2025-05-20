import time
import json
import logging
from locust import HttpUser
from requests.models import Response
from helper.prepare_headers import prepare_headers
from helper.prepare_params import prepare_params

# Configure file logging (only once per session/module)
logging.basicConfig(
    filename="locust_requests.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

class BasePage:
    def __init__(self, client: HttpUser, bearer_token: str = None, console_logging: bool = False):
        self.client = client
        self.bearer_token = bearer_token
        self.console_logging = console_logging

    def get(self, endpoint: str, headers: dict = None, params: dict = None) -> Response:
            headers = prepare_headers(headers, self.bearer_token)
            params = prepare_params(params)
            start = time.time()
            response = self.client.get(endpoint, headers=headers, params=params)
            self._log_and_time_request("GET", endpoint, response, time.time() - start)
            return response
        
    def put(self, endpoint: str, data: dict = None, json_data: dict = None, headers: dict = None) -> Response:
        if data is not None and json_data is not None:
            raise ValueError("Cannot provide both 'data' and 'json_data'. Choose one.")

        headers = self._prepare_headers(headers)
        start = time.time()
        if json_data:
            response = self.client.put(endpoint, json=json_data, headers=headers)
        else:
            response = self.client.put(endpoint, data=data, headers=headers)
        self._log_and_time_request("PUT", endpoint, response, time.time() - start)
        return response

    def delete(self, endpoint: str, headers: dict = None) -> Response:
        headers = self._prepare_headers(headers)
        start = time.time()
        response = self.client.delete(endpoint, headers=headers)
        self._log_and_time_request("DELETE", endpoint, response, time.time() - start)
        return response

    def assert_status_code(self, response: Response, expected_code: int):
        if response.status_code != expected_code:
            message = f"Expected {expected_code}, but got {response.status_code}. Response body: {response.text}"
            self.log(message)
            raise AssertionError(message)

    def get_json(self, response: Response):
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as e:
            self.log(f"Failed to parse JSON: {e}")
            return None


    def _log_and_time_request(self, method_name: str, endpoint: str, response: Response, duration: float) -> None:
        log_data = {
            "method": method_name.upper(),
            "url": response.url,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
            "response_size_bytes": len(response.content),
        }

        try:
            log_data["response_snippet"] = response.text[:200]
        except Exception as e:
            log_data["response_snippet"] = f"Error reading response text: {e}"

        message = f"[{method_name.upper()}] {endpoint} - {response.status_code} in {log_data['duration_ms']}ms"

        if self.console_logging:
            print(message)

        logging.info(json.dumps(log_data))

    def log(self, message: str):
        if self.console_logging:
            print(f"[BasePage Log] {message}")
        logging.info(message)

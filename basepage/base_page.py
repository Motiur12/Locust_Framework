import time
import json
import logging
from locust import HttpUser
from requests.models import Response
from helper.prepare_headers import prepare_headers
from helper.prepare_params import prepare_params
from helper.log_and_time_request import log_and_time_request


class BasePage:
    def __init__(self, client: HttpUser, bearer_token: str = None, console_logging: bool = False):
        self.client = client
        self.bearer_token = bearer_token
        self.console_logging = console_logging

    ##============================GET============================##
    def get(self, endpoint: str, headers: dict = None, params: dict = None) -> Response:
            headers = prepare_headers(headers, self.bearer_token)
            params = prepare_params(params)
            start = time.time()
            response = self.client.get(endpoint, headers=headers, params=params)
            log_and_time_request("GET", endpoint, response, duration=time.time() - start, console_logging=self.console_logging)
            return response
    
    ##============================POST============================##
    def post(self, endpoint: str, data: dict = None, json_data: dict = None, headers: dict = None) -> Response:
        return self._send_with_body("POST", endpoint, data, json_data, headers)
    
    def post_multipart(self, endpoint: str, data: dict = None, files: dict = None, headers: dict = None) -> Response:
        return self._send_multipart("POST", endpoint, data, files, headers)
    
    ##============================PUT============================##
    def put(self, endpoint: str, data: dict = None, json_data: dict = None, headers: dict = None) -> Response:
        return self._send_with_body("PUT", endpoint, data, json_data, headers)
    
    ##============================DELETE============================##
    def delete(self, endpoint: str, headers: dict = None) -> Response:
        headers = prepare_headers(headers)
        start = time.time()
        response = self.client.delete(endpoint, headers=headers)
        log_and_time_request("DELETE", endpoint, response, duration=time.time() - start, console_logging=self.console_logging)
        return response
    
    
    
    ##=======================================================================================================##
    def _send_with_body(self, method: str, endpoint: str, data: dict = None, json_data: dict = None, headers: dict = None) -> Response:
        self._check_data_and_json(data, json_data)
        headers = prepare_headers(headers)
        start = time.time()
        if json_data:
            response = getattr(self.client, method.lower())(endpoint, json=json_data, headers=headers)
        else:
            response = getattr(self.client, method.lower())(endpoint, data=data, headers=headers)
        log_and_time_request(method, endpoint, response, duration=time.time() - start, console_logging=self.console_logging)
        return response
    
    def _send_multipart(self, method: str, endpoint: str, data: dict = None, files: dict = None, headers: dict = None) -> Response:
        headers = prepare_headers(headers)
        start = time.time()
        method_func = getattr(self.client, method.lower())
        response = method_func(endpoint, data=data, files=files, headers=headers)
        log_and_time_request(method, endpoint, response, duration=time.time() - start, console_logging=self.console_logging)
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

    def log(self, message: str):
        if self.console_logging:
            print(f"[BasePage Log] {message}")
        logging.info(message)

    def _check_data_and_json(self, data, json_data):
        if data is not None and json_data is not None:
            raise ValueError("Cannot provide both 'data' and 'json_data'. Choose one.")

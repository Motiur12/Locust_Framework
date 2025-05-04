import os
import json
from helper import extract_from_response
from helper.config_reader import load_config

class BasePage:
    def __init__(self, client):
        self.client = client
        self.config = load_config()  # Load the config properties
        self.base_url = self.config.get("baseUrl")  # Get the base URL from config

    def get(self, url, **kwargs):
        full_url = f"{self.base_url}{url}"  # Prepend base_url to the endpoint
        response = self.client.get(full_url, **kwargs)
        self._log_response("GET", full_url, response)
        return response

    def post(self, url, data=None, json=None, **kwargs):
        full_url = f"{self.base_url}{url}"
        response = self.client.post(full_url, data=data, json=json, **kwargs)
        self._log_response("POST", full_url, response)

    def put(self, url, data=None, json=None, **kwargs):
        full_url = f"{self.base_url}{url}"
        response = self.client.put(full_url, data=data, json=json, **kwargs)
        self._log_response("PUT", full_url, response)
        return response

    def delete(self, url, **kwargs):
        full_url = f"{self.base_url}{url}"
        response = self.client.delete(full_url, **kwargs)
        self._log_response("DELETE", full_url, response)
        return response
    
    def post_json(self, url, json_path=None, extract_path=None, **kwargs):
        # Load JSON payload from file
        json_data = {}
        if json_path:
            if not os.path.exists(json_path):
                raise FileNotFoundError(f"JSON file not found: {json_path}")
            with open(json_path, 'r') as file:
                json_data = json.load(file)

        # Send POST request
        full_url = f"{self.base_url}{url}"
        response = self.client.post(full_url, json=json_data, **kwargs)
        self._log_response("POST", full_url, response)

        # Attempt to extract data from JSON response
        extracted_value = None
        if extract_path:
            try:
                extracted_value = extract_from_response(response.json(), extract_path)
            except Exception as e:
                print(f"❌ Failed to extract '{extract_path}': {e}")

        return extracted_value

    def _log_response(self, method, url, response):
        print(f"[{method}] {url} - Status: {response.status_code}")

import os
import json
from helper import extract_from_response
from helper.config_reader import load_config

class BasePage:
    def __init__(self, client):
        self.client = client
        self.config = load_config()  # Load the config properties
        self.base_url = self.config.get("baseUrl")  # Get the base URL from config

    def get(self, url, headers=None, **kwargs):
        full_url = f"{self.base_url}{url}"
        response = self.client.get(full_url, headers=headers, **kwargs)
        self._log_response("GET", full_url, response)
        return response

    def post(self, url, data=None, json=None, headers=None, files=None,**kwargs):
        full_url = f"{self.base_url}{url}"
        response = self.client.post(full_url, data=data, json=json, files=files, headers=headers, **kwargs)
        self._log_response("POST", full_url, response)
        return response

    def put(self, url, data=None, json=None, headers=None, **kwargs):
        full_url = f"{self.base_url}{url}"
        response = self.client.put(full_url, data=data, json=json, headers=headers, **kwargs)
        self._log_response("PUT", full_url, response)
        return response

    def delete(self, url, headers=None, **kwargs):
        full_url = f"{self.base_url}{url}"
        response = self.client.delete(full_url, headers=headers, **kwargs)
        self._log_response("DELETE", full_url, response)
        return response

    def post_json(self, url, json_path=None, extract_path=None, headers=None, **kwargs):
        json_data = {}
        if json_path:
            if not os.path.exists(json_path):
                raise FileNotFoundError(f"JSON file not found: {json_path}")
            with open(json_path, 'r') as file:
                json_data = json.load(file)

        full_url = f"{self.base_url}{url}"
        response = self.client.post(full_url, json=json_data, headers=headers, **kwargs)
        self._log_response("POST", full_url, response)

        extracted_value = None
        if extract_path:
            try:
                extracted_value = extract_from_response(response.json(), extract_path)
            except Exception as e:
                print(f"❌ Failed to extract '{extract_path}': {e}")

        return extracted_value


    def _log_response(self, method, url, response):
        print(f"[{method}] {url} - Status: {response.status_code}")

import os
import json
from helper import extract_from_response

class BasePage:
    
    def __init__(self, client):
        self.client = client

    def get(self, url, **kwargs):
        response = self.client.get(url, **kwargs)
        self._log_response("GET", url, response)
        return response

    def post(self, url, data=None, json=None, **kwargs):
        response = self.client.post(url, data=data, json=json, **kwargs)
        self._log_response("POST", url, response)

    def put(self, url, data=None, json=None, **kwargs):
        response = self.client.put(url, data=data, json=json, **kwargs)
        self._log_response("PUT", url, response)
        return response

    def delete(self, url, **kwargs):
        response = self.client.delete(url, **kwargs)
        self._log_response("DELETE", url, response)
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
        response = self.client.post(url, json=json_data, **kwargs)
        self._log_response("POST", url, response)

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

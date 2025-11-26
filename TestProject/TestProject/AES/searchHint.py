import os
import csv
import glob
import random
import threading
import itertools
import base64
from typing import List, Optional

from locust import HttpUser, task, between, constant

# Thread-safe SXSFR token storage and auto-update on 401
_sxsrf_lock = threading.Lock()
_sxsrf_token: Optional[str] = os.getenv('SXSRF_HEADER', '') or ''


def get_sxsrf_token() -> str:
	with _sxsrf_lock:
		return _sxsrf_token or ''


def _double_base64_encode(value: str) -> str:
	# encode to bytes, then base64 twice, return string
	b = value.encode('utf-8')
	e1 = base64.b64encode(b)
	e2 = base64.b64encode(e1)
	return e2.decode('utf-8')


def update_sxsrf_from_response(resp) -> None:
	"""If resp had HTTP 401 and header 'cf-ray-status-id-tn', update token."""
	try:
		if getattr(resp, 'status_code', None) == 401:
			hdr = resp.headers.get('cf-ray-status-id-tn') or resp.headers.get('CF-RAY-STATUS-ID-TN')
			if hdr:
				newtok = _double_base64_encode(hdr)
				with _sxsrf_lock:
					global _sxsrf_token
					_sxsrf_token = newtok
					# also update env var so external processes can see it if needed
					os.environ['SXSRF_HEADER'] = newtok
	except Exception:
		# be robust: do not fail on token update errors
		return


class CartupUser(HttpUser):
    wait_time = constant(1)
    host = "https://api.cartup.com"

    @task
    def search_hints(self):
        url = "/aes/api/v1/products/search-hints"

        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9,bn;q=0.8",
            "origin": "https://cartup.com",
            "priority": "u=1, i",
            "referer": "https://cartup.com/",
            "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            'sxsrf': get_sxsrf_token(),
            'user-agent': os.getenv('CLIENT_USER_AGENT', 'locust-load-test/1.0'),
            'next-router-prefetch': '1',
            'next-url': '/',
            'rsc': '1',
            'client-sdk': 'js5.7.1',
            'content-type': 'application/x-www-form-urlencoded',
        }

        res = self.client.get(url, headers=headers)
        update_sxsrf_from_response(res)

        #print(res.text)
        print(res.status_code)
        #print(res.headers)
        #print(res.json())
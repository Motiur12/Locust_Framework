import csv
import random
import glob
import os
from locust import HttpUser, task, between

def load_all_keywords():
    keywords = []
    csv_files = glob.glob(os.path.join(os.path.dirname(__file__), "keywords_chunk_*.csv"))
    
    for csv_path in csv_files:
        try:
            with open(csv_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                keywords.extend([row['keyword'].strip() for row in reader if row.get('keyword')])
        except Exception as e:
            print(f"Could not load {csv_path}: {e}")
    
    return keywords


class SearchUser(HttpUser):
    host = "http://10.20.4.20:30032"
    wait_time = between(1, 3)

    all_keywords = load_all_keywords()

    sxsrf_value = "V2xoc1MyVldiRmhPVjNScFRXcENjRlF5Y0VKa1ZURlZWVmhzVG1Gc1JYbFViWEJhWlZVNVZXRXpjRkJXUlZaNlUxYzFUMk5HYjNsT1IyeFFZVlZzTTFSWWNHdGhSbXhZVkZSU1lWSXhhekJVYlhCQ1RXc3dlVlpZYkU5V1IzaDBWRzV3YW1WVk5UWmFSekZQVmtWYWNGUlhNVlpsVlRsRlUxUlNVRlpIVW5CVVdIQktUVVV4Y1ZKdGJHRmhiRVYzVkRCa1MyRkdiRlZXYlRGT1ZqRkZlRlF3VW1wTk1YQjBVMVJDV2xZd05YQlRWMnd6WVZad1dXRklaR2hYUlhCeldUTnNTazVyTVZWWmVrcE9Va1pzTkZSWWNFNU5NRFZaVFVRd1BRPT0="

    def on_start(self):
        """Assign a unique random keyword to this user at start."""
        if not self.all_keywords:
            print("⚠️ No keywords loaded from CSV!")
            self.user_keyword = None
            return

        self.user_keyword = random.choice(self.all_keywords)
        self.all_keywords.remove(self.user_keyword)
        print(f"🟢 User {self} assigned keyword: {self.user_keyword}")

    @task
    def search_apis(self):
        if not self.all_keywords:
            print("⚠️ No keywords loaded from CSV!")
            return

        self.user_keyword = random.choice(self.all_keywords)

        headers = {"sxsrf": self.sxsrf_value}

        # --- API 1: tag-suggestions ---
        with self.client.get(
            "/aes/api/v1/products/tag-suggestions",
            params={"query": self.user_keyword},
            headers=headers,
            catch_response=True
        ) as response:
            print(f"[Tag-Suggestions] Keyword: {self.user_keyword}")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}\n")

            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"❌ Tag-Suggestions failed for keyword '{self.user_keyword}' (status: {response.status_code})")

        # --- API 2: search ---
        search_params = {
            "keyword": self.user_keyword,
            "sorting": 0,
            "rowsPerPage": 30,
            "currentPage": 1,
            "brandSlug": "",
            "categoryName": "",
            "maximumPrice": 1000000,
            "minimumPrice": 0,
            "rating": 0
        }

        with self.client.get(
            "/aes/api/v1/products/search",
            params=search_params,
            headers=headers,
            catch_response=True
        ) as response:
            print(f"[Search API] Keyword: {self.user_keyword}")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}\n")

            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"❌ Search API failed for keyword '{self.user_keyword}' (status: {response.status_code})")

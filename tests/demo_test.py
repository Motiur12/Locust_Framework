from locust import HttpUser, task
from pages.demo_page import UserPage

class UserAPITest(HttpUser):
    def on_start(self):
        self.user_page = UserPage(self.client)

    @task
    def test_get_user(self):
        response = self.user_page.get_user()
        if response.status_code == 200:
            print("✅ User fetched successfully.")
        else:
            print("❌ Failed to fetch user.")

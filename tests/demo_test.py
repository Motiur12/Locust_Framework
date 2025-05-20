from locust import HttpUser, task
from pages.demo_page import UserPage

class UserAPITest(HttpUser):
    def on_start(self):
        self.user_page = UserPage(self.client)

    @task
    def test_get_user(self):
        response = self.user_page.get_user()
        assert response.status_code == 200, f"GET user failed: {response.status_code}"
        # assert "user" in response.json(), "User data not found in response"

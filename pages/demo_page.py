from utils.base_page import BasePage

class UserPage(BasePage):
    def get_user(self, user_id=2):
        url = f"/api/users/{user_id}"
        headers = {
            "Content-Type": "application/json"
        }
        return self.get(url, headers=headers)

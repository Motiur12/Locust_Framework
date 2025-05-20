from basepage.base_page import BasePage
from requests.models import Response

class ListPage(BasePage):
    def __init__(self, client, bearer_token=None, console_logging=False):
        super().__init__(client, bearer_token, console_logging)

    def get_users(self, params=None, headers=None) -> Response:
        return self.get("/api/users", headers=headers, params=params)

    def assert_status(self, response: Response, expected_code: int):
 
        self.assert_status_code(response, expected_code)

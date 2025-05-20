from basepage.base_page import BasePage
from helper.save_response_data_to_csv import save_single_value_to_csv  # Make sure this import is correct
from requests import Response  # Add this import if you are using the requests library

class ListPage(BasePage):
    def __init__(self, client, bearer_token=None, console_logging=False):
        super().__init__(client, bearer_token, console_logging)

    def save_user_id_from_page_2(self):
        response = self.get("/api/users", params={"page": 2})
        self.assert_status_code(response, 200)

        save_single_value_to_csv(
            response=response,
            json_path="data.0.id",
            csv_file_path="output/users_page_2.csv",
            header="User ID"
        )


from pages.list import ListPage
from helper.save_response_data_to_csv import save_single_value_to_csv
from locust import HttpUser, task, between

class ReqresUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.list_page = ListPage(self.client, console_logging=True)

    @task
    def test_get_users_page_2(self):
            response = self.list_page.get_users(params={"page": 2})
            self.list_page.assert_status(response, 200)

            # Save data[0].id to CSV
            save_single_value_to_csv(
                response=response,
                json_path="data.0.id",
                csv_file_path="output/users_page_2.csv"
            )

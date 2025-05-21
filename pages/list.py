from basepage.base_page import BasePage
from helper.save_response_data_to_csv import save_single_value_to_csv  
from requests import Response
from helper.read_random_value_from_csv import read_random_value_from_csv
from helper.extract_value_from_json import extract_value_from_json
  
class ListPage(BasePage):
    def __init__(self, client, bearer_token=None, console_logging=False):
        super().__init__(client, bearer_token, console_logging)
        
    def get_list_of_users(self):
        response = self.get("/api/users", params={"page": 2})
        self.assert_status_code(response, 200)
        user_ids =extract_value_from_json(response, "data.0.id")
        print(user_ids)
    

    def save_user_id_from_page_2(self):
        response = self.get("/api/users", params={"page": 2})
        self.assert_status_code(response, 200)

        save_single_value_to_csv(
            response=response,
            json_path="data.0.id",
            csv_file_path="output/users_page_2.csv",
            header=["User ID"]
        )
        
    def post_user(self):
        response = self.post("/api/users", 
                             json_data={"name": read_random_value_from_csv("output/users_page_2.csv","Name" ), "job": "leader"},
                             headers={"Content-Type": "application/json","x-api-key": "reqres-free-v1"})
        print(response.text)
        
    def get_id_from_get_and_pass_to_post(self):
        response = self.get("/api/users", params={"page": 2})
        self.assert_status_code(response, 200)
        
        # Extract the user ID from the response
        user_id = self.extract_value_from_json(response, "data.0.id")
        
        # Use the extracted user ID in a POST request
        post_response = self.post("/api/users", 
                                  json_data={"name": read_random_value_from_csv("output/users_page_2.csv","Name" ), "job": "leader"},
                                  headers={"Content-Type": "application/json","x-api-key": "reqres-free-v1"})
        print(post_response.text)



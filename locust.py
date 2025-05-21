from pages.list import ListPage
from helper.logging_setup import setup_file_logging

setup_file_logging()

from locust import HttpUser, task, between

class ReqresUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        print("==================Starting Test====================")
        self.list_page = ListPage(self.client, console_logging=True)

##    @task
##    def test_get_users_page_2(self):
##       self.list_page.save_user_id_from_page_2()
        
    @task
    def test_get_users(self):
        self.list_page.get_list_of_users()

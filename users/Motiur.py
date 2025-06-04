from locust import HttpUser, task, between
from pages.list import ListPage
from prometheus_helper.prometheus_listeners import track_task_duration

class Motiur(HttpUser):
    wait_time = between(5, 10)

    def on_start(self):
        print("🚀 Starting Motiur")
        self.list_page = ListPage(self.client, console_logging=True)

    @task
    @track_task_duration("get_list_of_users")
    def get_list_of_users(self):
        self.list_page.get_list_of_users()
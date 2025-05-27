from locust import HttpUser, task, between

class LightUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def light_task(self):
        # Your light user task here
        pass

class HeavyUser(HttpUser):
    wait_time = between(2, 5)

    @task
    def heavy_task(self):
        # Your heavy user task here
        pass

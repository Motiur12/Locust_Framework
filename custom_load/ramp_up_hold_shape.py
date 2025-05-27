from locust import LoadTestShape
from demoLocustfile import LightUser, HeavyUser  # adjust import as needed

class RampUpHoldShape(LoadTestShape):
    ramp_time = 300  # seconds
    max_users = 100

    def tick(self):
        run_time = self.get_run_time()
        if run_time < self.ramp_time:
            user_count = int((run_time / self.ramp_time) * self.max_users)
        else:
            user_count = self.max_users

        spawn_rate = 10 if run_time < self.ramp_time else 0

        # Split users: 70% LightUser, 30% HeavyUser
        light_users = int(user_count * 0.7)
        heavy_users = user_count - light_users

        return (user_count, spawn_rate, [LightUser, HeavyUser])

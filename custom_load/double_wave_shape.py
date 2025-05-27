import math
from locust import LoadTestShape
from demoLocustfile import LightUser, HeavyUser

class DoubleWaveShape(LoadTestShape):
    time_limit = 120  # seconds

    def tick(self):
        run_time = self.get_run_time()
        if run_time > self.time_limit:
            return None  # stop test

        # Oscillate user count with sine wave (0 to 200 users)
        total_users = int(100 * (1 + math.sin(run_time * math.pi / 30)))
        spawn_rate = 20

        # Split users between LightUser and HeavyUser
        # Example: 70% LightUser, 30% HeavyUser
        light_users = int(total_users * 0.7)
        heavy_users = total_users - light_users

        # Return a tuple with users, spawn_rate, and user_classes
        return (light_users + heavy_users, spawn_rate, [LightUser, HeavyUser])

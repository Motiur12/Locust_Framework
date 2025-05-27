import random
from locust import LoadTestShape
from demoLocustfile import LightUser, HeavyUser  # Import your user classes

class RandomSpikeShape(LoadTestShape):
    def tick(self):
        run_time = self.get_run_time()
        base_users = 50
        spike = 0
        if random.random() < 0.1:  # 10% chance every tick for a spike
            spike = random.randint(50, 150)
        
        total_users = base_users + spike
        spawn_rate = 20
        
        # Split users between LightUser and HeavyUser, e.g., 60% light, 40% heavy
        light_users = int(total_users * 0.6)
        heavy_users = total_users - light_users
        
        # Return total users, spawn rate, and user classes
        return (total_users, spawn_rate, [LightUser, HeavyUser])

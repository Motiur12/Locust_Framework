from locust import LoadTestShape
from locustfile import LightUser, HeavyUser

class AdvancedLoadShape(LoadTestShape):
    use_common_options = True

    stages = [
        {"duration": 3,  "users": 10,  "spawn_rate": 5,  "user_classes": [LightUser]},
        {"duration": 6, "users": 30,  "spawn_rate": 10, "user_classes": [LightUser]},
        {"duration": 9, "users": 50,  "spawn_rate": 15, "user_classes": [LightUser, HeavyUser]},
        {"duration": 12, "users": 40,  "spawn_rate": 10, "user_classes": [HeavyUser]},
    ]

    def tick(self):
        run_time = self.get_run_time()

        total_duration = 0
        for stage in self.stages:
            total_duration += stage["duration"]
            if run_time < total_duration:
                return (stage["users"], stage["spawn_rate"], stage["user_classes"])

        # Loop the last stage forever with a minimal safe spawn rate
        last_stage = self.stages[-1]
        return (last_stage["users"], 1, last_stage["user_classes"])

    
    ### locust -f demoLocustfile.py,stage_load_shape.py --host=http://your-api-url.com

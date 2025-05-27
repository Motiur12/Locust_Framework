from locust import LoadTestShape
from demoLocustfile import LightUser, HeavyUser

class AdvancedLoadShape(LoadTestShape):
    use_common_options = True

    stages = [
        {"duration": 60,  "users": 10,  "spawn_rate": 5,  "user_classes": [LightUser]},
        {"duration": 120, "users": 30,  "spawn_rate": 10, "user_classes": [LightUser]},
        {"duration": 180, "users": 50,  "spawn_rate": 15, "user_classes": [LightUser, HeavyUser]},
        {"duration": 240, "users": 40,  "spawn_rate": 10, "user_classes": [HeavyUser]},
    ]

    def tick(self):
        run_time = self.get_run_time()
        current_users = self.get_current_user_count()

        total_duration = 0
        for stage in self.stages:
            total_duration += stage["duration"]
            if run_time < total_duration:
                if current_users < stage["users"]:
                    return (stage["users"], stage["spawn_rate"], stage["user_classes"])
                else:
                    return None

        return None
    
    ### locust -f demoLocustfile.py,stage_load_shape.py --host=http://your-api-url.com

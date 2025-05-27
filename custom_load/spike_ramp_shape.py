from locust import LoadTestShape
from demoLocustfile import LightUser, HeavyUser  # Import your user classes here

class SpikeRampShape(LoadTestShape):
    """
    Total duration: 8 minutes (480 seconds)
    Phase 1: 0–120 seconds → Gradually ramp up from 0 to 50 users (mostly LightUser)
    Phase 2: 120–180 seconds → Spike: 50 to 200 users (mix of LightUser and HeavyUser)
    Phase 3: 180–360 seconds → Gradually ramp down from 200 to 50 users (mostly HeavyUser)
    Phase 4: 360–480 seconds → Slowly decrease from 50 to 0 users (end)
    """

    def tick(self):
        run_time = self.get_run_time()

        if run_time < 120:
            user_count = int(run_time / 2.4)
            # Mostly LightUsers during ramp up
            return (user_count, 5, [LightUser])

        elif run_time < 180:
            # Spike: mixed LightUser and HeavyUser
            return (200, 20, [LightUser, HeavyUser])

        elif run_time < 360:
            down_rate = (run_time - 180) / 3.6
            user_count = 200 - int(down_rate)
            # Mostly HeavyUsers during ramp down
            return (user_count, 5, [HeavyUser])

        elif run_time < 480:
            user_count = 50 - int((run_time - 360) / 2.4)
            return (user_count, 2, [LightUser])

        return None  # Stop test

    
    ### locust -f demoLocustfile.py,spike_ramp_shape.py --host=http://your-api-url.com

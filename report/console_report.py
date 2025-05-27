from collections import defaultdict
import datetime

class ConsoleReport:
    def __init__(self, stages):
        self.stages = stages
        self.start_time = None
        self.end_time = None
        self.stage_metrics = []

        for stage in stages:
            self.stage_metrics.append({
                "requests": 0,
                "failures": 0,
                "total_response_time": 0.0,
                "user_counts": defaultdict(int)
            })

    def on_test_start(self, **kwargs):
        self.start_time = datetime.datetime.now()

    def on_request(self, request_type, name, response_time, response_length, context, exception, **kwargs):
        success = exception is None
        self._record_request(response_time, success)

    def _record_request(self, response_time, success):
        if self.start_time is None:
            return

        elapsed = (datetime.datetime.now() - self.start_time).total_seconds()
        stage_idx = self._get_stage_index(elapsed)
        if stage_idx is None:
            return

        stage = self.stage_metrics[stage_idx]
        stage["requests"] += 1
        if not success:
            stage["failures"] += 1
        stage["total_response_time"] += response_time

    def _get_stage_index(self, elapsed):
        total_time = 0
        for i, stage in enumerate(self.stages):
            total_time += stage["duration"]
            if elapsed < total_time:
                return i
        return None

    def on_test_stop(self, **kwargs):
        self.end_time = datetime.datetime.now()
        self.print_report()

    def print_report(self):
        if self.start_time is None or self.end_time is None:
            print("Test timing information incomplete. Skipping report.")
            return

        duration = (self.end_time - self.start_time).total_seconds()

        print("\n\n========= CUSTOM LOAD TEST REPORT =========")
        print(f"Test Start Time : {self.start_time}")
        print(f"Test End Time   : {self.end_time}")
        print(f"Total Duration  : {duration:.2f} seconds\n")

        print("Time (s)  Users (Total)  Users (LightUser)  Users (HeavyUser)  RPS (Req/sec)  Avg Resp Time (ms)  Failures  Notes")
        print("---------------------------------------------------------------------------------------------------------------")

        total_time = 0
        for i, stage in enumerate(self.stages):
            total_time += stage["duration"]
            metrics = self.stage_metrics[i]
            total_requests = metrics["requests"]
            failures = metrics["failures"]
            avg_resp_time = (metrics["total_response_time"] / total_requests) if total_requests > 0 else 0
            rps = total_requests / stage["duration"] if stage["duration"] > 0 else 0

            total_users = stage["users"]
            user_class_names = [cls.__name__ for cls in stage["user_classes"]]
            light_users = total_users if user_class_names == ["LightUser"] else total_users // 2
            heavy_users = total_users - light_users

            notes = "LightUser load" if user_class_names == ["LightUser"] else (
                    "HeavyUser load" if user_class_names == ["HeavyUser"] else "Mixed load")

            time_range = f"{total_time - stage['duration']} - {total_time}"

            print(f"{time_range:^9} {total_users:^13} {light_users:^17} {heavy_users:^18} {rps:^13.1f} {avg_resp_time:^18.1f} {failures:^9} {notes}")

        print(f"{total_time}+{'':>7} {'0':>13} {'0':>17} {'0':>18} {'0':>13} {'0':>18} {'0':>9} Test stopped")
        print("===============================================================================================================\n")

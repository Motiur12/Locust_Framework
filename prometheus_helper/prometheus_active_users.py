import time
import threading
from prometheus.prometheusMetrics import ACTIVE_USERS

def update_active_users(env, interval=2):
    while True:
        if not env.runner:
            time.sleep(1)
            continue
        for user_class in env.runner.user_classes:
            count = env.runner.user_classes_count.get(user_class, 0)
            ACTIVE_USERS.labels(user_class=user_class.__name__).set(count)
        time.sleep(interval)

def start_active_users_updater(environment):
    thread = threading.Thread(target=update_active_users, args=(environment,), daemon=True)
    thread.start()

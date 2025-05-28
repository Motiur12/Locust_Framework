from flask import Flask, render_template, request, redirect, url_for
import os
from jinja2 import Template

app = Flask(__name__)

# 🟡 Path to your actual 'users' folder (outside the GUI directory)
USERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'users'))

USER_TEMPLATE = """from locust import HttpUser, task, between
from pages.list import {{ page_class }}
from prometheus_helper.prometheus_listeners import track_task_duration

class {{ classname }}(HttpUser):
    wait_time = between({{ wait_min }}, {{ wait_max }})

    def on_start(self):
        print("🚀 Starting {{ classname }}")
        self.list_page = {{ page_class }}(self.client, console_logging=True)

    @task
    @track_task_duration("{{ task_name }}")
    def {{ task_name }}(self):
        self.list_page.{{ task_name }}()
"""

def get_user_classes():
    return [
        f.split('.')[0] for f in os.listdir(USERS_DIR)
        if f.endswith('.py') and not f.startswith('__')
    ]

@app.route('/')
def index():
    user_classes = get_user_classes()
    message = request.args.get('message')
    return render_template('index.html', user_classes=user_classes, message=message)

@app.route('/create_user', methods=['POST'])
def create_user():
    classname = request.form['classname']
    file_path = os.path.join(USERS_DIR, f"{classname}.py")

    if os.path.exists(file_path):
        # Redirect back to index with error message
        return redirect(url_for('index', message=f"❌ User class '{classname}' already exists!"))

    wait_min = request.form['wait_min']
    wait_max = request.form['wait_max']
    page_class = request.form['page_class']
    task_name = request.form['task_name']

    user_code = Template(USER_TEMPLATE).render(
        classname=classname,
        wait_min=wait_min,
        wait_max=wait_max,
        page_class=page_class,
        task_name=task_name
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(user_code)

    return redirect(url_for('index', message=f"✅ User class '{classname}' created successfully."))

@app.route('/delete_user/<classname>', methods=['POST'])
def delete_user(classname):
    file_path = os.path.join(USERS_DIR, f"{classname}.py")
    if os.path.exists(file_path):
        os.remove(file_path)
        return redirect(url_for('index', message=f"✅ User class '{classname}' deleted successfully."))
    else:
        return redirect(url_for('index', message=f"❌ User class '{classname}' not found."))

@app.route('/run_test', methods=['POST'])
def run_test():
    user_class = request.form['user_class']
    users = request.form['users']
    spawn_rate = request.form['spawn_rate']
    duration = request.form['duration']

    os.system(f"locust -f ../locustfile.py --headless -u {users} -r {spawn_rate} -t {duration} --class-name {user_class}")
    return redirect(url_for('index', message=f"✅ Started Locust test with {user_class}"))

if __name__ == '__main__':
    app.run(debug=True)


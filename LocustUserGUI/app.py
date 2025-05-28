from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
from jinja2 import Template

app = Flask(__name__)

# Path to your actual 'users' folder (outside the GUI directory)
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

# Helper: get user classes from USERS_DIR
def get_user_classes():
    return [
        f.split('.')[0] for f in os.listdir(USERS_DIR)
        if f.endswith('.py') and not f.startswith('__')
    ]

@app.route('/')
def index():
    # Render main page with user classes for dropdown and list
    user_classes = get_user_classes()
    return render_template('index.html', user_classes=user_classes)

@app.route('/create_user', methods=['POST'])
def create_user():
    classname = request.form['classname'].strip()
    file_path = os.path.join(USERS_DIR, f"{classname}.py")

    if os.path.exists(file_path):
        return f"❌ User class '{classname}' already exists!", 400

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

    return redirect(url_for('index'))

@app.route('/user_classes', methods=['GET'])
def user_classes_api():
    # API endpoint for returning user classes as JSON (optional for AJAX)
    return jsonify(get_user_classes())

@app.route('/run_test', methods=['POST'])
def run_test():
    user_class = request.form['user_class']
    users = request.form['users']
    spawn_rate = request.form['spawn_rate']
    duration = request.form['duration']

    # Replace below with your actual locust file and parameters if needed
    os.system(f"locust -f ../locustfile.py --headless -u {users} -r {spawn_rate} -t {duration} --class-name {user_class}")
    return f"✅ Started Locust test with {user_class}"

if __name__ == '__main__':
    app.run(debug=True)

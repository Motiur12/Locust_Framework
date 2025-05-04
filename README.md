# 🚀 Locust Performance Testing Framework

This repository is a modular and scalable performance testing framework using [Locust](https://locust.io/) for simulating user behavior and testing APIs under load.

---

## 📁 Key Files

### 🔹 `locustfile.py`

- Entry point for Locust.
- Defines user class and tasks.
- Imports test logic via wrapper classes or test modules.

### 🔹 `run_locust.py`

- Custom script to launch Locust in headless mode (CLI).
- Dynamically loads configuration and runs the load test without requiring UI.
- Ideal for automation or CI/CD environments.

---

## 🚀 How to Run

### 🖥️ 1. Run Locust Web UI (Manual)

```bash
locust -f locustfile.py
```

- Opens a web interface at: http://localhost:8089
- Enter the number of users, spawn rate, and target host to start the test.

### 🤖 🖥️ 1. Run Locust Web UI (Manual)

```bash
python run_locust.py
```

- This runs the test directly from the terminal using preset values.
- Outputs performance metrics live in your terminal.
- Great for scheduled or automated test runs.

### 🧪 Add or Modify Tests

- Write API tests or logic inside the tests/ directory.
- If needed, wrap reusable logic inside the wrapper/ directory.
- Import and use them inside locustfile.py to define behavior.

### 🧹 Clean __pycache__ (Optional)

# Windows:
```bash
clean_pycache.bat
```
# Linux/macOS:
```bash
./clean_pycache.sh
```
- run those files for clearing the cache.
  
### 🧠 Tips

- Keep your locustfile.py minimal—delegate logic to test or wrapper classes.
- Use run_locust.py for automation; it's designed to run tests with zero manual input.
- Organize your tests and locators cleanly for reuse and maintainability.







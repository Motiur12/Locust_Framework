
# 🐛 Locust Load Testing Framework with Playwright & Prometheus Integration

This repository provides a modular and extensible **Locust-based performance testing framework** with support for:

- ✅ Headless browser automation using **Playwright**
- ✅ Multi-browser support (Chromium, Edge, etc.)
- ✅ Advanced metrics via **Prometheus**
- ✅ Dockerized test execution
- ✅ Custom load shapes and stages
- ✅ Console reporting and modular design

---

## 📁 Project Structure

```bash
.
├── locustfile.py              # Main Locust test entry point
├── custom_load/               # Custom load shapes and stages
├── pages/                     # Page Object Models for Playwright
├── users/                     # User behavior definitions
├── basepage/                  # BasePage for Playwright POM structure
├── helper/                    # Utility functions and helpers
├── prometheus/                # Prometheus config files
├── prometheus_helper/         # Prometheus metric integration for Locust
├── report/                    # (Optional) Load test reports
├── command.bat / command.txt  # Sample commands to run tests
├── Dockerfile.locust          # Dockerfile for Locust environment
├── docker-compose.yml         # Docker compose for running Locust and Prometheus
└── requirements.txt           # Python dependencies
```

---

## 🚀 Features

- ✅ Use **Playwright** for browser-based user flows (login, navigation, etc.)
- ✅ Assign **different browsers per user** (e.g., Chromium, Edge)
- ✅ Use **Prometheus** for live metrics and Grafana dashboards
- ✅ **Modular test design** using POM and custom users
- ✅ Optional: integrate with CI pipelines for performance regression

---

## 🧰 Setup Instructions

### 🔧 Prerequisites

- Python 3.9+
- Node.js (for Playwright)
- Docker (if running in containers)

### 🐍 Install Dependencies

```bash
pip install -r requirements.txt
playwright install
```

### ▶️ Run Locust Test (Locally)

```bash
locust -f locustfile.py
```

Access the UI at: [http://localhost:8089](http://localhost:8089)

### 🐳 Run with Docker

```bash
docker-compose up --build
```

---

## 🌐 Multi-Browser Playwright Integration

Each virtual user can be configured to launch different browsers like:

```python
# In users/ or locustfile.py
edge_path = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
self.browser = await self.playwright.chromium.launch(
    executable_path=edge_path, headless=True
)
```

Alternate users between Chromium and Edge with a modulo on the user index.

---

## 📈 Prometheus Monitoring

Prometheus configuration is available under `prometheus/`. You can start it with:

```bash
docker-compose up
```

Then open:

- **Locust Web UI**: [http://localhost:8089](http://localhost:8089)
- **Prometheus**: [http://localhost:9090](http://localhost:9090)

Grafana dashboard support can be added if needed.

---

## 🧪 Sample Test Scenarios

Check the `users/` folder for user flows using Playwright automation:

- Login tests
- Form submissions
- Navigation + assertions

---

## 📦 To Do

- [ ] Add Grafana dashboards
- [ ] Export detailed reports to HTML/CSV
- [ ] Integrate with CI/CD
- [ ] Add retry logic and logging

---

## 🧑‍💻 Author

Developed by **Motiur Rahman**  
Quality Assurance Engineer | Python & JavaScript Enthusiast

---

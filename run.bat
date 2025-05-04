@echo off
echo 📦 Installing dependencies...

REM Upgrade pip and install requirements silently
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt >nul 2>&1

if %errorlevel% neq 0 (
    echo ❌ Dependency installation failed!
    exit /b %errorlevel%
)

echo ✅ All dependencies installed successfully.
pause


@REM echo 🚀 Starting Locust with Prometheus exporter enabled...
@REM locust --host=http://your-target-site.com --enable-prometheus-exporter --prometheus-export-port=9646


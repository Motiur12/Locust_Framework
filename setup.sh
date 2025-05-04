#!/bin/bash
# (Linux/macOS)


echo "🔧 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# echo "🚀 Running Locust..."
# locust --host=http://your-target-site.com --enable-prometheus-exporter --prometheus-export-port=9646

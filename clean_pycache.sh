#!/bin/bash

echo "Deleting __pycache__ folders and .pyc files..."

# Delete __pycache__ directories
find . -type d -name "__pycache__" -exec rm -rf {} + -print

# Delete .pyc files
find . -type f -name "*.pyc" -exec rm -f {} + -print

echo "Cleanup complete."

# helper/logging_setup.py
"""
The `setup_file_logging` function sets up logging to a file and console with a specific format in
Python.

:param log_file: The `log_file` parameter in the `setup_file_logging` function is a string that
specifies the name of the log file where the log messages will be written. By default, the log
messages will be written to a file named "locust_requests.log" unless a different file name is
provided when, defaults to locust_requests.log (optional)
"""
import logging
import sys

def setup_file_logging(log_file="locust_requests.log"):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Remove any existing handlers to avoid duplicate logs
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    file_handler = logging.FileHandler(log_file, mode='w')
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
import csv
import logging
from requests import Response
from json import JSONDecodeError
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def get_value_by_path(json_data: dict, path: str):
    keys = path.split(".")
    value = json_data
    try:
        for key in keys:
            if isinstance(value, list) and key.isdigit():
                value = value[int(key)]
            else:
                value = value[key]
        return value
    except (KeyError, TypeError, IndexError) as e:
        logger.error(f"Failed to get value at path: {path}", exc_info=True)
        return None
    


def save_single_value_to_csv(response: Response, json_path: str, csv_file_path: str, header: str = None):
    try:
        data = response.json()
    except JSONDecodeError as e:
        logger.error(f"Invalid JSON response: {e}")
        return

    value = get_value_by_path(data, json_path)
    if value is None:
        logger.error(f"No value found at path '{json_path}'")
        return

    # Prepare CSV file: if doesn't exist, write header first
    file_exists = os.path.isfile(csv_file_path)
    try:
        with open(csv_file_path, mode='a', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            if not file_exists and header:
                writer.writerow(header)  # Header as the path
            writer.writerow([value])
        logger.info(f"Value saved to CSV: {csv_file_path}")
    except Exception as e:
        logger.error(f"Error writing to CSV: {e}")

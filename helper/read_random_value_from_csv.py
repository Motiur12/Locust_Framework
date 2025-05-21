import csv
import random

def read_random_value_from_csv(csv_path: str, column_name: str) -> str:
    values = []
    with open(csv_path, mode='r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if value := row.get(column_name):
                values.append(value)
    if not values:
        raise ValueError(f"No data found for column: {column_name}")
    return random.choice(values)

import json

def extract_value_from_json(response, path):
    try:
        data = response.json()
        for key in path.split('.'):
            data = data[int(key)] if key.isdigit() else data[key]
        return data
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as e:
        print(f"Failed to extract value from JSON path '{path}': {e}")
        return None
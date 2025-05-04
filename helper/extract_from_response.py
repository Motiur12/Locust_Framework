def extract_from_response(data, path):
    keys = path.split('.')
    for key in keys:
        data = data[key]
    return data

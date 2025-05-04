import configparser
import os

def load_config(file_path="config/config.properties"):
    config = configparser.ConfigParser()
    config.read_dict({"DEFAULT": {}})
    if os.path.exists(file_path):
        config.read(file_path)
    else:
        raise FileNotFoundError(f"❌ Config file not found: {file_path}")
    return config["DEFAULT"]

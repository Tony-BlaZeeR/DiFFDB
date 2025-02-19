from enum import Enum

class AppConfig(Enum):
    CONNECTION_FILE_PATH = "config/DB.txt"

def get_config(config: AppConfig):
    return config.value
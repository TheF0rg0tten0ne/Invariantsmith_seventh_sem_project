import json


def load_settings(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}

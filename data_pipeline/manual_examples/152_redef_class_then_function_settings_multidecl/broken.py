import json


class Settings:
    def __init__(self):
        self.debug = False


def Settings(debug=False):
    return json.dumps({"debug": debug})

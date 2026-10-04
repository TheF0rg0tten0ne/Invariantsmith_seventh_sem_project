import json


def Settings(debug=False):
    return json.dumps({"debug": debug})

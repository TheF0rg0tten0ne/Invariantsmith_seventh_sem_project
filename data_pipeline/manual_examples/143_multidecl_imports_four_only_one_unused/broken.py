import json
import os
import sys
import re


def load_and_echo(path):
    with open(path) as fh:
        data = json.load(fh)
    print(os.path.basename(path), file=sys.stderr)
    return data

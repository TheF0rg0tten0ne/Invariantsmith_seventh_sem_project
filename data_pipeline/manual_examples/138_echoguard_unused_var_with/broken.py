def line_count(path):
    with open(path) as f:
        return len(open(path).readlines())

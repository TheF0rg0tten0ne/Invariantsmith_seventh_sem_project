def line_count(path):
    with open(path):
        return len(open(path).readlines())

def parse_int(value):
    try:
        parsed = int(value)
        return int(value)
    except ValueError:
        return None

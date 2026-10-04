def scale(values, factor):
    if factor == 0:
        return []
    return [v * factor for v in values]

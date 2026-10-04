def flatten(nested: list) -> list:
    result = []
    for group in nested:
        result.extend(group)
    return result

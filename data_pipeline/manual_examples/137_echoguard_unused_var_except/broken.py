def try_convert(text):
    try:
        return int(text)
    except ValueError as err:
        return None

def try_convert(text):
    try:
        return int(text)
    except ValueError:
        return None

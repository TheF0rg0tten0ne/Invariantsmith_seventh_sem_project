def safe_parse(text):
    try:
        return int(text)
    except ValueError
        return 0

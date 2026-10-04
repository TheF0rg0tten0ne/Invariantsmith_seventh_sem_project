def load_settings(path):
    try:
        return parse_settings_file(path)
    except FileNotFoundError:
        return {}

DEFAULT_KEY = "id"


def build_request(**kwargs):
    return kwargs.get(DEFAULT_KEY, "unset")

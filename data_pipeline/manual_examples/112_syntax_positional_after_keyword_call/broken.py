def build_url(host, port):
    return f"{host}:{port}"


def make_request():
    return build_url(host="localhost", 8080)

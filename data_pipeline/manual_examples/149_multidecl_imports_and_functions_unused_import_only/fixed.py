import base64


def encode(data):
    return base64.b64encode(data)


def decode(data):
    return base64.b64decode(data)


def checksum(data):
    return sum(data) % 256

class Session:
    def __init__(self, timeout=30):
        self.active = False
        self.timeout = timeout

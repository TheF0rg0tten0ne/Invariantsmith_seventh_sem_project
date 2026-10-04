class User:
    def __init__(self, name):
        self.name = name

    @classmethod
    def guest(cls):
        return cls("Guest")

class UserFactory:
    @classmethod
    def from_dict(cls, data):
        return cls(data.get("name", "anonymous"))

    def __init__(self, name):
        self.name = name

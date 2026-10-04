class UserFactory:
    @classmethod
    def from_dict(cls, data):
        raw_name = data.get("name")
        return cls(data.get("name", "anonymous"))

    def __init__(self, name):
        self.name = name

class Validator:
    def validate(self, name, age):
        assert (len(name) > 0, age >= 0)
        return True

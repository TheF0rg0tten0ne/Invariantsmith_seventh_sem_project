class Validator:
    def validate(self, name, age):
        assert len(name) > 0 and age >= 0
        return True

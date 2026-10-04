class Guard:
    def check(self, a, b, c):
        assert a and b and c
        return True

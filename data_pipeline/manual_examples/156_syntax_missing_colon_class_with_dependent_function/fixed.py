class Shape:
    def area(self):
        return 0


def describe(shape):
    return f"{type(shape).__name__}: {shape.area()}"

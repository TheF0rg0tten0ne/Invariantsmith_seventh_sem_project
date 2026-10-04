class Circle:
    def __init__(self, radius):
        self.radius = radius

    @property
    def area(self):
        return PI * self.radius ** 2

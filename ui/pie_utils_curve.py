class Point:
    def __init__(self, x=0.0, y=0.0):
        self.x = x
        self.y = y

    def set(self, x, y):
        self.x = x
        self.y = y

    def copy_from(self, other):
        self.x = other.x
        self.y = other.y

    def as_tuple(self):
        return (self.x, self.y)

    def __repr__(self):
        return f"Point(x={self.x}, y={self.y})"

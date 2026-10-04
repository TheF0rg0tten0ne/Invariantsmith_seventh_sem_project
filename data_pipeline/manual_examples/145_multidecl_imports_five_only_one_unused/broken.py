import csv
import io
import math
import collections
import datetime


def load_rows(text):
    reader = csv.reader(io.StringIO(text))
    return list(reader)


def circle_area(radius):
    return math.pi * radius ** 2


def tally(items):
    return collections.Counter(items)

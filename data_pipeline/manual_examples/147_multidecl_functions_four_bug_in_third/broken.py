def celsius_to_fahrenheit(c):
    return c * 9 / 5 + 32


def fahrenheit_to_celsius(f):
    return (f - 32) * 5 / 9


def celsius_to_kelvin(c):
    return c + kelvin_offset


def kelvin_to_celsius(k):
    return k - 273.15

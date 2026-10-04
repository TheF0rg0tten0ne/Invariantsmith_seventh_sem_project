class TemperatureConverter:
    @staticmethod
    def to_fahrenheit(celsius):
        return celsius * 9 / 5 + FREEZING_OFFSET

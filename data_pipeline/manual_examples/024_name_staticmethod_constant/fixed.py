class TemperatureConverter:
    FREEZING_OFFSET = 32

    @staticmethod
    def to_fahrenheit(celsius):
        return celsius * 9 / 5 + TemperatureConverter.FREEZING_OFFSET

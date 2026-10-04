def describe(value):
    if value > 0:
        label = "positive"
    elif value < 0:
        label = "negative"
    return f"{value} is {label_default}"

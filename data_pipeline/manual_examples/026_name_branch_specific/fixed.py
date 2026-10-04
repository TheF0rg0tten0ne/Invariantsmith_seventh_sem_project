def describe(value):
    if value > 0:
        label = "positive"
    elif value < 0:
        label = "negative"
    else:
        label = "zero"
    return f"{value} is {label}"

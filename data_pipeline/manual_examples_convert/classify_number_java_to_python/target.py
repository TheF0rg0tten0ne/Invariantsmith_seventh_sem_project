def classify(n):
    if n > 0:
        return "positive"
    elif n < 0:
        return "negative"
    return "zero"


if __name__ == "__main__":
    print(classify(-7))

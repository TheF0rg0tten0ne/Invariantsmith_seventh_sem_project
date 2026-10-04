def validate_age(age):
    if age < 0:
        return False
    if age > 150:
        return False
    return True

def validate_age(age):
    is_valid = age >= 0
    if age < 0:
        return False
    if age > 150:
        return False
    return True

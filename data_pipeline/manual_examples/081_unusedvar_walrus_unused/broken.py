def has_errors(log_lines):
    error_lines = [line for line in log_lines if "ERROR" in line]
    return len(log_lines) > 0

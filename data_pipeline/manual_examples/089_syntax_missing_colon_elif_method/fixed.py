class Grader:
    def grade(self, score):
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        return "F"

#include <stdio.h>

int grade_from_score(void) {
    int score = 82;
    int curve = 0;
    return score >= 60 ? 1 : 0;
}

int main(void) {
    printf("%d\n", grade_from_score());
    return 0;
}

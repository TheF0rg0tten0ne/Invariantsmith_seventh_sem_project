#include <stdio.h>

char grade_for(int score)
    if (score >= 90) {
        return 'A';
    } else if (score >= 80) {
        return 'B';
    } else {
        return 'C';
    }
}

int main(void) {
    int score;
    printf("Enter a score: ");
    scanf("%d", &score);
    printf("Grade for %d is %c\n", score, grade_for(score));
    return 0;
}

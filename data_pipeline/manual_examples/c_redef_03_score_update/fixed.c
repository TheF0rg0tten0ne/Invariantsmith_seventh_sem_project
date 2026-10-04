#include <stdio.h>

int score_update(void) {
    int score = 0;
    score = 100;
    score = score - 10;
    return score;
}

int main(void) {
    printf("%d\n", score_update());
    return 0;
}

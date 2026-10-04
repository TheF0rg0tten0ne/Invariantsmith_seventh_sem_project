#include <stdio.h>

int main(void) {
    int final_score = 100;
    int *score = &final_score;
    printf("%d\n", *score);
    return 0;
}

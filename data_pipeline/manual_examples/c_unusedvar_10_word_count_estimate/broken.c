#include <stdio.h>

int word_count_estimate(void) {
    int chars = 500;
    int avg_word_len = 5;
    return chars / 5;
}

int main(void) {
    printf("%d\n", word_count_estimate());
    return 0;
}

#include <stdio.h>

int word_count_estimate(void) {
    int chars = 500;
    return chars / 5;
}

int main(void) {
    printf("%d\n", word_count_estimate());
    return 0;
}

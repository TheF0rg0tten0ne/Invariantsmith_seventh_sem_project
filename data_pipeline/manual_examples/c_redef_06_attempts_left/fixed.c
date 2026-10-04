#include <stdio.h>

int attempts_left(void) {
    int attempts = 3;
    attempts = attempts - 1;
    attempts = attempts - 1;
    return attempts;
}

int main(void) {
    printf("%d\n", attempts_left());
    return 0;
}

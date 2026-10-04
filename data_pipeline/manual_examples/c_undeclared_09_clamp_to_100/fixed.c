#include <stdio.h>

int clamp_to_100(int x) {
    return x > 100 ? 100 : x;
}

int main(void) {
    printf("%d\n", clamp_to_100(5));
    return 0;
}

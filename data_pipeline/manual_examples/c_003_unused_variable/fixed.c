#include <stdio.h>

int main(void) {
    int total = 0;
    for (int i = 0; i < 5; i++) {
        total += i;
    }
    printf("Total: %d\n", total);
    return 0;
}

#include <stdio.h>

int main(void) {
    int value = 5;
    int *count = &value;
    printf("%d\n", *count);
    return 0;
}

#include <stdio.h>

int main(void) {
    int array_size = 12;
    int *size = &array_size;
    printf("%d\n", *size);
    return 0;
}

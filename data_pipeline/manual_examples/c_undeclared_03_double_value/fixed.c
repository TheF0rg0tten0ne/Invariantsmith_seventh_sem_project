#include <stdio.h>

int double_value(int v) {
    return v * 2;
}

int main(void) {
    printf("%d\n", double_value(5));
    return 0;
}

#include <stdio.h>

int main(void) {
    int status_code = 404;
    int *code = &status_code;
    printf("%d\n", *code);
    return 0;
}

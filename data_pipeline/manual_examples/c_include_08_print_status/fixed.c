#include <stdio.h>

int print_status(void) {
    printf("Status: %s\n", "OK");
    return 0;
}

int main(void) {
    return print_status();
}

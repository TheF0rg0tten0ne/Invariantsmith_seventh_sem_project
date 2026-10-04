#include <stdio.h>

void print_temp(int degrees, int is_celsius) {
    printf(is_celsius ? "%dC\n" : "%dF\n", degrees);
}

int main(void) {
    return 0;
}

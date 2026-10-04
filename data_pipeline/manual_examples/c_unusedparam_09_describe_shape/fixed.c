#include <stdio.h>

void describe_shape(int sides, int is_regular) {
    printf(is_regular ? "regular %d-gon\n" : "%d-gon\n", sides);
}

int main(void) {
    return 0;
}

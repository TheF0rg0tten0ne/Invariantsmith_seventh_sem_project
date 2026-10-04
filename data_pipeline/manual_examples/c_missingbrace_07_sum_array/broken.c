#include <stdio.h>

int sum_array(void)
    int total = 0;
    for (int i = 0; i < 3; i++) total += i;
    return total;
}

int main(void) {
    return sum_array();
    return 0;
}

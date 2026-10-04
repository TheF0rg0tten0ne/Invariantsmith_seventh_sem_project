#include <stdio.h>

int distance_km_to_m(void) {
    int km = 3;
    return km * 1000;
}

int main(void) {
    printf("%d\n", distance_km_to_m());
    return 0;
}

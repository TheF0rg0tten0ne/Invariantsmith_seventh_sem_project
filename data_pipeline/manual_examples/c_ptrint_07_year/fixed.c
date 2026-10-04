#include <stdio.h>

int main(void) {
    int release_year = 2026;
    int *year = &release_year;
    printf("%d\n", *year);
    return 0;
}

#include <stdio.h>

int retry_count(void) {
    int retries = 0;
    retries = retries + 1;
    retries = retries + 1;
    return retries;
}

int main(void) {
    printf("%d\n", retry_count());
    return 0;
}

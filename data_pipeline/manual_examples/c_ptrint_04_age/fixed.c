#include <stdio.h>

int main(void) {
    int person_age = 30;
    int *age = &person_age;
    printf("%d\n", *age);
    return 0;
}

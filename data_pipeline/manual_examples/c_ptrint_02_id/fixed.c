#include <stdio.h>

int main(void) {
    int user_id = 42;
    int *id = &user_id;
    printf("%d\n", *id);
    return 0;
}

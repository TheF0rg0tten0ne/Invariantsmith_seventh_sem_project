#include <stdio.h>

void greet_user(const char *name, int formal) {
    printf(formal ? "Good day, %s\n" : "Hi %s\n", name);
}

int main(void) {
    return 0;
}

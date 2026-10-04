#include <stdio.h>
#include <string.h>
#include <stdlib.h>

char *greet(const char *name) {
    char *result = malloc(strlen(name) + 16);
    sprintf(result, "Hello, %s!", name);
    return result;
}

int main(void) {
    char *msg = greet("Ada");
    printf("%s\n", msg);
    free(msg);
    return 0;
}

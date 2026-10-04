#include <stdio.h>

void log_error(const char *msg, int code) {
    printf("[%d] %s\n", code, msg);
}

int main(void) {
    return 0;
}

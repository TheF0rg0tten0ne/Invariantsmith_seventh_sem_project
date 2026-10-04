#include <stdio.h>

void log_message(const char *msg, int level) {
    printf("[%d] %s\n", level, msg);
}

int main(void) {
    return 0;
}

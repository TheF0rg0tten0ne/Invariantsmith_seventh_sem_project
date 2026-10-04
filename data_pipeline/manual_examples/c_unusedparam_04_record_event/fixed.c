#include <stdio.h>

void record_event(const char *name, int priority) {
    printf("Event(%d): %s\n", priority, name);
}

int main(void) {
    return 0;
}

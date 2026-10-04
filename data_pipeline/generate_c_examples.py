"""
One-shot generator for a much larger batch of C manual_examples/, covering
6 real (gcc-verified) error classes across 10 different domain scenarios
each, instead of one hand-typed example per class.

This is a dev tool, not part of the shipped pipeline -- run it once,
inspect the output, delete it (or keep it around to regenerate/extend
later). Every example is checked against error_detector.analyze() at
generation time so bad templates fail loudly here instead of silently
producing a REJECTED line in build_manual_dataset.py's output.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import error_detector  # noqa: E402

OUT = Path(__file__).parent / "manual_examples"

# --------------------------------------------------------------------
# Class 1: undeclared identifier -- function body references a name that
# was never declared/passed, when a real parameter/local was clearly
# intended.
# --------------------------------------------------------------------
UNDECLARED = [
    ("square", "int n", "return result * result;", "return n * n;",
     "'result' doesn't exist -- the function's real parameter is 'n', which is what should be squared."),
    ("cube", "int x", "return num * num * num;", "return x * x * x;",
     "'num' doesn't exist -- the function's real parameter is 'x'."),
    ("double_value", "int v", "return value * 2;", "return v * 2;",
     "'value' doesn't exist -- the function's real parameter is 'v'."),
    ("average_of_two", "int a, int b", "return (first + b) / 2;", "return (a + b) / 2;",
     "'first' doesn't exist -- the function's real first parameter is 'a'."),
    ("celsius_to_fahrenheit", "int c", "return (temp * 9 / 5) + 32;", "return (c * 9 / 5) + 32;",
     "'temp' doesn't exist -- the function's real parameter is 'c'."),
    ("circle_area_x100", "int radius", "return 314 * r * r / 100;", "return 314 * radius * radius / 100;",
     "'r' doesn't exist -- the function's real parameter is 'radius'."),
    ("max_of_two", "int a, int b", "return (first > b) ? first : b;", "return (a > b) ? a : b;",
     "'first' doesn't exist -- the function's real first parameter is 'a'."),
    ("is_even", "int n", "return number % 2 == 0;", "return n % 2 == 0;",
     "'number' doesn't exist -- the function's real parameter is 'n'."),
    ("clamp_to_100", "int x", "return value > 100 ? 100 : value;", "return x > 100 ? 100 : x;",
     "'value' doesn't exist -- the function's real parameter is 'x'."),
    ("triple_value", "int amount", "return total * 3;", "return amount * 3;",
     "'total' doesn't exist -- the function's real parameter is 'amount'."),
]

# --------------------------------------------------------------------
# Class 2: unused variable -- a local is declared and never read/written
# again anywhere in the function.
# --------------------------------------------------------------------
UNUSED_VAR = [
    ("sum_to_five", "int i, total = 0;\n    int scratch = 0;\n    for (i = 1; i <= 5; i++) {\n        total += i;\n    }\n    return total;",
     "int i, total = 0;\n    for (i = 1; i <= 5; i++) {\n        total += i;\n    }\n    return total;",
     "scratch"),
    ("count_positive", "int count = 0;\n    int debug_mode = 1;\n    int nums[3] = {1, -2, 3};\n    for (int i = 0; i < 3; i++) {\n        if (nums[i] > 0) count++;\n    }\n    return count;",
     "int count = 0;\n    int nums[3] = {1, -2, 3};\n    for (int i = 0; i < 3; i++) {\n        if (nums[i] > 0) count++;\n    }\n    return count;",
     "debug_mode"),
    ("apply_discount", "int price = 100;\n    int discount_flag = 1;\n    return price - 10;",
     "int price = 100;\n    return price - 10;",
     "discount_flag"),
    ("grade_from_score", "int score = 82;\n    int curve = 0;\n    return score >= 60 ? 1 : 0;",
     "int score = 82;\n    return score >= 60 ? 1 : 0;",
     "curve"),
    ("inventory_remaining", "int stock = 40, sold = 12;\n    int reorder_point = 5;\n    return stock - sold;",
     "int stock = 40, sold = 12;\n    return stock - sold;",
     "reorder_point"),
    ("distance_km_to_m", "int km = 3;\n    char unit = 'k';\n    return km * 1000;",
     "int km = 3;\n    return km * 1000;",
     "unit"),
    ("temperature_alert", "int temp = 90;\n    int last_reading = 0;\n    return temp > 85 ? 1 : 0;",
     "int temp = 90;\n    return temp > 85 ? 1 : 0;",
     "last_reading"),
    ("battery_percent_ok", "int percent = 15;\n    int prev_percent = 0;\n    return percent > 20 ? 1 : 0;",
     "int percent = 15;\n    return percent > 20 ? 1 : 0;",
     "prev_percent"),
    ("shopping_cart_total", "int a = 5, b = 10;\n    int tax_rate = 0;\n    return a + b;",
     "int a = 5, b = 10;\n    return a + b;",
     "tax_rate"),
    ("word_count_estimate", "int chars = 500;\n    int avg_word_len = 5;\n    return chars / 5;",
     "int chars = 500;\n    return chars / 5;",
     "avg_word_len"),
]

# --------------------------------------------------------------------
# Class 3: redefinition -- a variable already declared in scope gets
# re-declared (with a type) instead of just reassigned.
# --------------------------------------------------------------------
REDEFINITION = [
    ("counter_increment", "int count = 0;\n    count = count + 1;\n    int count = count + 1;\n    return count;",
     "int count = 0;\n    count = count + 1;\n    count = count + 1;\n    return count;", "count"),
    ("running_total", "int total = 10;\n    total += 5;\n    int total = total + 1;\n    return total;",
     "int total = 10;\n    total += 5;\n    total = total + 1;\n    return total;", "total"),
    ("score_update", "int score = 0;\n    score = 100;\n    int score = score - 10;\n    return score;",
     "int score = 0;\n    score = 100;\n    score = score - 10;\n    return score;", "score"),
    ("balance_after_fee", "int balance = 500;\n    balance -= 20;\n    int balance = balance - 5;\n    return balance;",
     "int balance = 500;\n    balance -= 20;\n    balance = balance - 5;\n    return balance;", "balance"),
    ("level_up", "int level = 1;\n    level = level + 1;\n    int level = level * 2;\n    return level;",
     "int level = 1;\n    level = level + 1;\n    level = level * 2;\n    return level;", "level"),
    ("attempts_left", "int attempts = 3;\n    attempts = attempts - 1;\n    int attempts = attempts - 1;\n    return attempts;",
     "int attempts = 3;\n    attempts = attempts - 1;\n    attempts = attempts - 1;\n    return attempts;", "attempts"),
    ("queue_size", "int size = 0;\n    size = size + 1;\n    int size = size + 1;\n    return size;",
     "int size = 0;\n    size = size + 1;\n    size = size + 1;\n    return size;", "size"),
    ("temperature_reading", "int temp = 20;\n    temp = temp + 2;\n    int temp = temp - 1;\n    return temp;",
     "int temp = 20;\n    temp = temp + 2;\n    temp = temp - 1;\n    return temp;", "temp"),
    ("page_number", "int page = 1;\n    page = page + 1;\n    int page = page + 1;\n    return page;",
     "int page = 1;\n    page = page + 1;\n    page = page + 1;\n    return page;", "page"),
    ("retry_count", "int retries = 0;\n    retries = retries + 1;\n    int retries = retries + 1;\n    return retries;",
     "int retries = 0;\n    retries = retries + 1;\n    retries = retries + 1;\n    return retries;", "retries"),
]

# --------------------------------------------------------------------
# Class 4: pointer/int conversion -- initializing a pointer with a bare
# int literal instead of a real address.
# --------------------------------------------------------------------
PTR_INT = [
    ("count", 5, "value"), ("id", 42, "user_id"), ("score", 100, "final_score"),
    ("age", 30, "person_age"), ("qty", 7, "item_qty"), ("level", 1, "player_level"),
    ("year", 2026, "release_year"), ("balance", 250, "account_balance"),
    ("size", 12, "array_size"), ("code", 404, "status_code"),
]

# --------------------------------------------------------------------
# Class 5: unused parameter (-Wunused-parameter, requires -Wextra which
# error_detector already passes).
# --------------------------------------------------------------------
UNUSED_PARAM = [
    ("log_message", "const char *msg, int level", "printf(\"%s\\n\", msg);",
     "printf(\"[%d] %s\\n\", level, msg);", "level"),
    ("greet_user", "const char *name, int formal", "printf(\"Hi %s\\n\", name);",
     "printf(formal ? \"Good day, %s\\n\" : \"Hi %s\\n\", name);", "formal"),
    ("print_price", "int cents, int with_symbol", "printf(\"%d\\n\", cents);",
     "printf(with_symbol ? \"$%d\\n\" : \"%d\\n\", cents);", "with_symbol"),
    ("record_event", "const char *name, int priority", "printf(\"Event: %s\\n\", name);",
     "printf(\"Event(%d): %s\\n\", priority, name);", "priority"),
    ("format_name", "const char *first, const char *last", "printf(\"%s\\n\", first);",
     "printf(\"%s %s\\n\", first, last);", "last"),
    ("apply_tax", "int amount, int rate", "printf(\"%d\\n\", amount);",
     "printf(\"%d\\n\", amount + amount * rate / 100);", "rate"),
    ("show_progress", "int done, int total", "printf(\"%d\\n\", done);",
     "printf(\"%d/%d\\n\", done, total);", "total"),
    ("log_error", "const char *msg, int code", "printf(\"%s\\n\", msg);",
     "printf(\"[%d] %s\\n\", code, msg);", "code"),
    ("describe_shape", "int sides, int is_regular", "printf(\"%d\\n\", sides);",
     "printf(is_regular ? \"regular %d-gon\\n\" : \"%d-gon\\n\", sides);", "is_regular"),
    ("print_temp", "int degrees, int is_celsius", "printf(\"%d\\n\", degrees);",
     "printf(is_celsius ? \"%dC\\n\" : \"%dF\\n\", degrees);", "is_celsius"),
]

# --------------------------------------------------------------------
# Class 6: missing #include <stdio.h> despite calling printf.
# --------------------------------------------------------------------
MISSING_INCLUDE = [
    ("print_hello", 'printf("Hello, world!\\n");'),
    ("print_sum", 'printf("%d\\n", 2 + 2);'),
    ("print_name", 'printf("Name: %s\\n", "Ada");'),
    ("print_temp_c", 'printf("%d C\\n", 21);'),
    ("print_count", 'printf("Count: %d\\n", 10);'),
    ("print_score", 'printf("Score: %d\\n", 95);'),
    ("print_balance", 'printf("Balance: %d\\n", 500);'),
    ("print_status", 'printf("Status: %s\\n", "OK");'),
    ("print_year", 'printf("Year: %d\\n", 2026);'),
    ("print_ratio", 'printf("%d/%d\\n", 3, 4);'),
]

# --------------------------------------------------------------------
# Class 7: missing opening brace after a function signature. gcc's
# recovery from this is a cascade -- it reports several DOWNSTREAM lines
# as "expected declaration specifiers before 'x'" rather than pointing
# at the actual missing '{' -- this is exactly the shape of error the
# production model was seen misdiagnosing (as a "missing return type",
# which is wrong: the return type is right there) on a real user report.
# --------------------------------------------------------------------
MISSING_BRACE = [
    ("main", "void", "printf(\"Hello, world!\\n\");\n    return 0;",
     'printf("Hello, world!\\n");\n    return 0;'),
    ("compute_total", "int",
     "int a = 5, b = 10;\n    return a + b;",
     "int a = 5, b = 10;\n    return a + b;"),
    ("print_report", "void",
     "printf(\"Report\\n\");\n    printf(\"Done\\n\");",
     "printf(\"Report\\n\");\n    printf(\"Done\\n\");"),
    ("classify", "int",
     "int n = 5;\n    if (n > 0) return 1;\n    return 0;",
     "int n = 5;\n    if (n > 0) return 1;\n    return 0;"),
    ("run_checks", "int",
     "int ok = 1;\n    return ok;",
     "int ok = 1;\n    return ok;"),
    ("log_event", "void",
     "printf(\"Event logged\\n\");",
     "printf(\"Event logged\\n\");"),
    ("sum_array", "int",
     "int total = 0;\n    for (int i = 0; i < 3; i++) total += i;\n    return total;",
     "int total = 0;\n    for (int i = 0; i < 3; i++) total += i;\n    return total;"),
    ("show_menu", "void",
     "printf(\"1. Start\\n\");\n    printf(\"2. Quit\\n\");",
     "printf(\"1. Start\\n\");\n    printf(\"2. Quit\\n\");"),
]


def _write(slug: str, broken: str, fixed: str, rationale: str, confidence: float = 0.9,
           target_error_index: int | str | None = None):
    d = OUT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "broken.c").write_text(broken)
    (d / "fixed.c").write_text(fixed)

    # Fail fast: verify broken.c actually trips something before ever
    # handing this to build_manual_dataset.py.
    errs = error_detector.analyze(broken, "buffer.c", "c")
    if not errs:
        raise AssertionError(f"{slug}: broken.c triggers NOTHING -- bad template")

    # Some templates (e.g. a missing brace) cascade into several errors --
    # pick the first genuine syntax-severity one rather than assuming
    # index 0 is always it.
    if target_error_index == "first_syntax":
        target_error_index = next((i for i, e in enumerate(errs) if e.severity == "syntax"), 0)

    meta = {"language": "c", "rationale": rationale, "confidence": confidence}
    if target_error_index is not None:
        meta["target_error_index"] = target_error_index
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return len(errs)


def main():
    n = 0
    for i, (fn, params, broken_body, fixed_body, rationale) in enumerate(UNDECLARED, 1):
        # main()'s call must match the function's real arity, or the
        # "fixed" version fails verification with 'too few arguments'
        # instead of being accepted as a clean fix.
        call_args = "5" if params.count(",") == 0 else "5, 3"
        broken = f'#include <stdio.h>\n\nint {fn}({params}) {{\n    {broken_body}\n}}\n\nint main(void) {{\n    printf("%d\\n", {fn}({call_args}));\n    return 0;\n}}\n'
        fixed = f'#include <stdio.h>\n\nint {fn}({params}) {{\n    {fixed_body}\n}}\n\nint main(void) {{\n    printf("%d\\n", {fn}({call_args}));\n    return 0;\n}}\n'
        _write(f"c_undeclared_{i:02d}_{fn}", broken, fixed, rationale, target_error_index=0)
        n += 1

    for i, (fn, decls, decls_fixed, unused_name) in enumerate(UNUSED_VAR, 1):
        broken = f'#include <stdio.h>\n\nint {fn}(void) {{\n    {decls}\n}}\n\nint main(void) {{\n    printf("%d\\n", {fn}());\n    return 0;\n}}\n'
        fixed = f'#include <stdio.h>\n\nint {fn}(void) {{\n    {decls_fixed}\n}}\n\nint main(void) {{\n    printf("%d\\n", {fn}());\n    return 0;\n}}\n'
        rationale = f"'{unused_name}' is declared but never read or written anywhere else in the function -- remove it."
        _write(f"c_unusedvar_{i:02d}_{fn}", broken, fixed, rationale)
        n += 1

    for i, (fn, decls, decls_fixed, var_name) in enumerate(REDEFINITION, 1):
        broken = f'#include <stdio.h>\n\nint {fn}(void) {{\n    {decls}\n}}\n\nint main(void) {{\n    printf("%d\\n", {fn}());\n    return 0;\n}}\n'
        fixed = f'#include <stdio.h>\n\nint {fn}(void) {{\n    {decls_fixed}\n}}\n\nint main(void) {{\n    printf("%d\\n", {fn}());\n    return 0;\n}}\n'
        rationale = f"'{var_name}' is already declared above; the second 'int {var_name} = ...' redeclares it in the same scope instead of just reassigning it."
        _write(f"c_redef_{i:02d}_{fn}", broken, fixed, rationale)
        n += 1

    for i, (var, val, real_var) in enumerate(PTR_INT, 1):
        broken = f'#include <stdio.h>\n\nint main(void) {{\n    int *{var} = {val};\n    printf("%d\\n", *{var});\n    return 0;\n}}\n'
        fixed = f'#include <stdio.h>\n\nint main(void) {{\n    int {real_var} = {val};\n    int *{var} = &{real_var};\n    printf("%d\\n", *{var});\n    return 0;\n}}\n'
        rationale = f"'{var}' is declared as int*, but {val} is an int literal, not an address -- point it at a real int's address instead."
        _write(f"c_ptrint_{i:02d}_{var}", broken, fixed, rationale)
        n += 1

    for i, (fn, params, broken_body, fixed_body, unused_param) in enumerate(UNUSED_PARAM, 1):
        broken = f'#include <stdio.h>\n\nvoid {fn}({params}) {{\n    {broken_body}\n}}\n\nint main(void) {{\n    return 0;\n}}\n'
        fixed = f'#include <stdio.h>\n\nvoid {fn}({params}) {{\n    {fixed_body}\n}}\n\nint main(void) {{\n    return 0;\n}}\n'
        rationale = f"'{unused_param}' is a parameter that's never read in the function body -- use it, or the caller's intent is silently dropped."
        _write(f"c_unusedparam_{i:02d}_{fn}", broken, fixed, rationale)
        n += 1

    for i, (fn, call) in enumerate(MISSING_INCLUDE, 1):
        broken = f'int {fn}(void) {{\n    {call}\n    return 0;\n}}\n\nint main(void) {{\n    return {fn}();\n}}\n'
        fixed = f'#include <stdio.h>\n\nint {fn}(void) {{\n    {call}\n    return 0;\n}}\n\nint main(void) {{\n    return {fn}();\n}}\n'
        rationale = "printf() requires <stdio.h>; without it the declaration is implicit and undefined behavior on strict compilers."
        _write(f"c_include_{i:02d}_{fn}", broken, fixed, rationale, target_error_index=0)
        n += 1

    for i, (fn, ret_type, body, body_fixed) in enumerate(MISSING_BRACE, 1):
        rationale = (
            f"'{fn}' is missing its opening '{{' -- without it, gcc parses the body's "
            f"statements as if they were file-scope declarations, which is what produces "
            f"the cascade of 'expected declaration specifiers' errors on every line after it, "
            f"not just the first one. Adding the '{{' (and the matching closing '}}' this "
            f"function already had) resolves the whole cascade at once."
        )
        if fn == "main":
            # The reported production case: the function under test IS
            # main itself, no separate driver needed.
            broken = f'#include <stdio.h>\n\nint main()\n    {body}\n}}\n'
            fixed = f'#include <stdio.h>\n\nint main() {{\n    {body_fixed}\n}}\n'
        else:
            call = "" if ret_type == "void" else f'printf("%d\\n", {fn}());\n    '
            call_stmt = f"{fn}();" if ret_type == "void" else f"return {fn}();"
            broken = (f'#include <stdio.h>\n\n{ret_type} {fn}(void)\n    {body}\n}}\n\n'
                       f'int main(void) {{\n    {call_stmt}\n    return 0;\n}}\n')
            fixed = (f'#include <stdio.h>\n\n{ret_type} {fn}(void) {{\n    {body_fixed}\n}}\n\n'
                      f'int main(void) {{\n    {call_stmt}\n    return 0;\n}}\n')
        _write(f"c_missingbrace_{i:02d}_{fn}", broken, fixed, rationale, target_error_index="first_syntax")
        n += 1

    print(f"Generated {n} C examples under {OUT}")


if __name__ == "__main__":
    main()

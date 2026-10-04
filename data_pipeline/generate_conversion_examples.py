"""
One-shot generator for manual_examples_convert/. Each of the 8 PROGRAMS
below is hand-written correctly in all 3 languages; the generator then
expands that into every directed pair (source_lang -> target_lang) among
the 3 supported languages, giving 8 * 6 = 48 conversion training
examples. Every source and target file is checked against
error_detector.analyze() at generation time -- same fail-fast philosophy
as generate_c_examples.py / generate_java_examples.py.
"""
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import error_detector, languages  # noqa: E402

OUT = Path(__file__).parent / "manual_examples_convert"

_EXT = {lid: languages.LANGUAGES[lid].extensions[0].lstrip(".") for lid in languages.LANGUAGE_ORDER}

# Each PROGRAMS entry: name -> {"python": src, "c": src, "java": src, "notes": str}
# "notes" describes anything non-trivial about translating this particular
# program's idioms across languages (matches what CONVERT_SYSTEM_PROMPT
# asks the model to report).
PROGRAMS = {
    "sum_of_list": {
        "python": (
            "def main():\n"
            "    nums = [4, 8, 15, 16, 23]\n"
            "    total = 0\n"
            "    for n in nums:\n"
            "        total += n\n"
            "    print(total)\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n"
        ),
        "c": (
            "#include <stdio.h>\n\n"
            "int main(void) {\n"
            "    int nums[5] = {4, 8, 15, 16, 23};\n"
            "    int total = 0;\n"
            "    for (int i = 0; i < 5; i++) {\n"
            "        total += nums[i];\n"
            "    }\n"
            "    printf(\"%d\\n\", total);\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "public class Main {\n"
            "    public static void main(String[] args) {\n"
            "        int[] nums = {4, 8, 15, 16, 23};\n"
            "        int total = 0;\n"
            "        for (int n : nums) {\n"
            "            total += n;\n"
            "        }\n"
            "        System.out.println(total);\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Python's list becomes a fixed-size array in C/Java since the length never changes; a for-each loop is the closest idiomatic match in all three.",
    },
    "classify_number": {
        "python": (
            "def classify(n):\n"
            "    if n > 0:\n"
            "        return \"positive\"\n"
            "    elif n < 0:\n"
            "        return \"negative\"\n"
            "    return \"zero\"\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(classify(-7))\n"
        ),
        "c": (
            "#include <stdio.h>\n\n"
            "const char *classify(int n) {\n"
            "    if (n > 0) {\n"
            "        return \"positive\";\n"
            "    } else if (n < 0) {\n"
            "        return \"negative\";\n"
            "    }\n"
            "    return \"zero\";\n"
            "}\n\n"
            "int main(void) {\n"
            "    printf(\"%s\\n\", classify(-7));\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "public class Main {\n"
            "    public static String classify(int n) {\n"
            "        if (n > 0) {\n"
            "            return \"positive\";\n"
            "        } else if (n < 0) {\n"
            "            return \"negative\";\n"
            "        }\n"
            "        return \"zero\";\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(classify(-7));\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Python's str return type maps to const char* in C (a string literal, so no allocation/freeing needed) and to String in Java.",
    },
    "fizzish_loop": {
        "python": (
            "def main():\n"
            "    for i in range(1, 11):\n"
            "        if i % 3 == 0:\n"
            "            print(\"Fizz\")\n"
            "        else:\n"
            "            print(i)\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n"
        ),
        "c": (
            "#include <stdio.h>\n\n"
            "int main(void) {\n"
            "    for (int i = 1; i <= 10; i++) {\n"
            "        if (i % 3 == 0) {\n"
            "            printf(\"Fizz\\n\");\n"
            "        } else {\n"
            "            printf(\"%d\\n\", i);\n"
            "        }\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "public class Main {\n"
            "    public static void main(String[] args) {\n"
            "        for (int i = 1; i <= 10; i++) {\n"
            "            if (i % 3 == 0) {\n"
            "                System.out.println(\"Fizz\");\n"
            "            } else {\n"
            "                System.out.println(i);\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Python's range(1, 11) is an exclusive upper bound, so it becomes the inclusive condition i <= 10 in C/Java's counted for-loop.",
    },
    "string_greeting": {
        "python": (
            "def greet(name):\n"
            "    return \"Hello, \" + name + \"!\"\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(greet(\"Ada\"))\n"
        ),
        "c": (
            "#include <stdio.h>\n"
            "#include <string.h>\n"
            "#include <stdlib.h>\n\n"
            "char *greet(const char *name) {\n"
            "    char *result = malloc(strlen(name) + 16);\n"
            "    sprintf(result, \"Hello, %s!\", name);\n"
            "    return result;\n"
            "}\n\n"
            "int main(void) {\n"
            "    char *msg = greet(\"Ada\");\n"
            "    printf(\"%s\\n\", msg);\n"
            "    free(msg);\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "public class Main {\n"
            "    public static String greet(String name) {\n"
            "        return \"Hello, \" + name + \"!\";\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(greet(\"Ada\"));\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Python and Java both garbage-collect string concatenation; C needs an explicit heap allocation for the returned string, which the caller must free -- a real ownership decision Python/Java don't force on you.",
    },
    "factorial_iterative": {
        "python": (
            "def factorial(n):\n"
            "    result = 1\n"
            "    for i in range(2, n + 1):\n"
            "        result *= i\n"
            "    return result\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(factorial(6))\n"
        ),
        "c": (
            "#include <stdio.h>\n\n"
            "long factorial(int n) {\n"
            "    long result = 1;\n"
            "    for (int i = 2; i <= n; i++) {\n"
            "        result *= i;\n"
            "    }\n"
            "    return result;\n"
            "}\n\n"
            "int main(void) {\n"
            "    printf(\"%ld\\n\", factorial(6));\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "public class Main {\n"
            "    public static long factorial(int n) {\n"
            "        long result = 1;\n"
            "        for (int i = 2; i <= n; i++) {\n"
            "            result *= i;\n"
            "        }\n"
            "        return result;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(factorial(6));\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Python's ints are arbitrary-precision, so factorial can't overflow there the way it can in C/Java -- using 'long' in both gives reasonable headroom for the same small input without pretending the overflow risk doesn't exist.",
    },
    "is_prime_check": {
        "python": (
            "def is_prime(n):\n"
            "    if n < 2:\n"
            "        return False\n"
            "    for d in range(2, n):\n"
            "        if n % d == 0:\n"
            "            return False\n"
            "    return True\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(is_prime(17))\n"
        ),
        "c": (
            "#include <stdio.h>\n"
            "#include <stdbool.h>\n\n"
            "bool is_prime(int n) {\n"
            "    if (n < 2) {\n"
            "        return false;\n"
            "    }\n"
            "    for (int d = 2; d < n; d++) {\n"
            "        if (n % d == 0) {\n"
            "            return false;\n"
            "        }\n"
            "    }\n"
            "    return true;\n"
            "}\n\n"
            "int main(void) {\n"
            "    printf(\"%s\\n\", is_prime(17) ? \"True\" : \"False\");\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "public class Main {\n"
            "    public static boolean isPrime(int n) {\n"
            "        if (n < 2) {\n"
            "            return false;\n"
            "        }\n"
            "        for (int d = 2; d < n; d++) {\n"
            "            if (n % d == 0) {\n"
            "                return false;\n"
            "            }\n"
            "        }\n"
            "        return true;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(isPrime(17));\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Python's bool prints as 'True'/'False' with a capital letter, so the C version prints matching literal strings for output parity; Java's boolean already prints lowercase 'true'/'false' by convention, left as-is rather than forced to match Python's casing.",
    },
    "average_of_array": {
        "python": (
            "def average(nums):\n"
            "    return sum(nums) // len(nums)\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(average([10, 20, 30, 40]))\n"
        ),
        "c": (
            "#include <stdio.h>\n\n"
            "int average(int nums[], int count) {\n"
            "    int total = 0;\n"
            "    for (int i = 0; i < count; i++) {\n"
            "        total += nums[i];\n"
            "    }\n"
            "    return total / count;\n"
            "}\n\n"
            "int main(void) {\n"
            "    int nums[4] = {10, 20, 30, 40};\n"
            "    printf(\"%d\\n\", average(nums, 4));\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "public class Main {\n"
            "    public static int average(int[] nums) {\n"
            "        int total = 0;\n"
            "        for (int n : nums) {\n"
            "            total += n;\n"
            "        }\n"
            "        return total / nums.length;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        int[] nums = {10, 20, 30, 40};\n"
            "        System.out.println(average(nums));\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Python's // is already integer division matching C/Java's default int/int division, and Java's array carries its own .length instead of needing a separate count parameter like C does.",
    },
    "celsius_to_fahrenheit": {
        "python": (
            "def celsius_to_fahrenheit(c):\n"
            "    return c * 9 / 5 + 32\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(celsius_to_fahrenheit(21))\n"
        ),
        "c": (
            "#include <stdio.h>\n\n"
            "double celsius_to_fahrenheit(double c) {\n"
            "    return c * 9.0 / 5.0 + 32.0;\n"
            "}\n\n"
            "int main(void) {\n"
            "    printf(\"%g\\n\", celsius_to_fahrenheit(21));\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "public class Main {\n"
            "    public static double celsiusToFahrenheit(double c) {\n"
            "        return c * 9.0 / 5.0 + 32.0;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(celsiusToFahrenheit(21));\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Python 3's / is always true division regardless of operand types, so C/Java need explicit double literals (9.0/5.0) to avoid silently truncating to integer division the way c * 9 / 5 would with plain ints.",
    },
    "read_int_and_echo": {
        "python": (
            "def main():\n"
            "    n = int(input())\n"
            "    print(f\"You entered: {n}\")\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n"
        ),
        "c": (
            "#include <stdio.h>\n\n"
            "int main(void) {\n"
            "    int n;\n"
            "    scanf(\"%d\", &n);\n"
            "    printf(\"You entered: %d\\n\", n);\n"
            "    return 0;\n"
            "}\n"
        ),
        "java": (
            "import java.util.Scanner;\n\n"
            "public class Main {\n"
            "    public static void main(String[] args) {\n"
            "        Scanner scanner = new Scanner(System.in);\n"
            "        int n = scanner.nextInt();\n"
            "        System.out.println(\"You entered: \" + n);\n"
            "    }\n"
            "}\n"
        ),
        "notes": "Reading stdin has no shared idiom across these three: Python's input() returns a str that needs int(), C's scanf writes through a pointer and returns a status code the caller usually checks, and Java needs an explicit java.util.Scanner instance wrapping System.in -- System.in itself is a raw InputStream with no readLine()/nextInt() of its own, a mistake the un-fine-tuned model made on exactly this program.",
    },
}


def _write(slug: str, src_lang: str, tgt_lang: str, source_code: str, target_code: str, notes: str):
    d = OUT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / f"source.{_EXT[src_lang]}").write_text(source_code)
    (d / f"target.{_EXT[tgt_lang]}").write_text(target_code)
    (d / "meta.json").write_text(json.dumps({"notes": notes}, indent=2) + "\n")

    for lang, code, label in ((src_lang, source_code, "source"), (tgt_lang, target_code, "target")):
        errs = error_detector.analyze(code, "buffer", lang)
        syntax_err = next((e for e in errs if e.severity == "syntax"), None)
        if syntax_err:
            raise AssertionError(f"{slug}: {label}.{_EXT[lang]} has a syntax error in {lang}: {syntax_err.message}")


def main():
    n = 0
    for name, spec in PROGRAMS.items():
        notes = spec["notes"]
        for src_lang, tgt_lang in itertools.permutations(languages.LANGUAGE_ORDER, 2):
            slug = f"{name}_{src_lang}_to_{tgt_lang}"
            _write(slug, src_lang, tgt_lang, spec[src_lang], spec[tgt_lang], notes)
            n += 1
    print(f"Generated {n} conversion examples under {OUT}")


if __name__ == "__main__":
    main()

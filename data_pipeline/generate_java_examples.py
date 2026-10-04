"""
One-shot generator for a much larger batch of Java manual_examples/,
covering 5 real (javac-verified) error classes across up to 10 domain
scenarios each. Same fail-fast philosophy as generate_c_examples.py --
every example is checked against error_detector.analyze() before it's
ever handed to build_manual_dataset.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import error_detector  # noqa: E402

OUT = Path(__file__).parent / "manual_examples"

# --------------------------------------------------------------------
# Class 1: cannot find symbol (javac's undeclared-name error).
# Return type is explicit per-entry: isEven returns boolean, not int,
# and hardcoding 'int' there produces an incompatible-types error in the
# *fixed* file, which fails verification.
# --------------------------------------------------------------------
CANNOT_FIND_SYMBOL = [
    ("square", "int", "int n", "return result * result;", "return n * n;",
     "'result' doesn't exist -- the method's real parameter is 'n'."),
    ("cube", "int", "int x", "return num * num * num;", "return x * x * x;",
     "'num' doesn't exist -- the method's real parameter is 'x'."),
    ("doubleValue", "int", "int v", "return value * 2;", "return v * 2;",
     "'value' doesn't exist -- the method's real parameter is 'v'."),
    ("celsiusToFahrenheit", "int", "int c", "return (temp * 9 / 5) + 32;", "return (c * 9 / 5) + 32;",
     "'temp' doesn't exist -- the method's real parameter is 'c'."),
    ("circleAreaX100", "int", "int radius", "return 314 * r * r / 100;", "return 314 * radius * radius / 100;",
     "'r' doesn't exist -- the method's real parameter is 'radius'."),
    ("isEven", "boolean", "int n", "return number % 2 == 0;", "return n % 2 == 0;",
     "'number' doesn't exist -- the method's real parameter is 'n'."),
    ("clampTo100", "int", "int x", "return value > 100 ? 100 : value;", "return x > 100 ? 100 : x;",
     "'value' doesn't exist -- the method's real parameter is 'x'."),
    ("tripleValue", "int", "int amount", "return total * 3;", "return amount * 3;",
     "'total' doesn't exist -- the method's real parameter is 'amount'."),
    ("halveValue", "int", "int amount", "return original / 2;", "return amount / 2;",
     "'original' doesn't exist -- the method's real parameter is 'amount'."),
    ("negate", "int", "int n", "return 0 - input;", "return 0 - n;",
     "'input' doesn't exist -- the method's real parameter is 'n'."),
]

# --------------------------------------------------------------------
# Class 2: missing return statement -- some path through a non-void
# method doesn't return a value, which javac rejects as a compile error
# (unlike gcc -fsyntax-only, javac's flow analysis IS reachable here).
# --------------------------------------------------------------------
MISSING_RETURN = [
    ("classify", "int n", "if (n > 0) {\n            return 1;\n        } else if (n < 0) {\n            return -1;\n        }",
     "if (n > 0) {\n            return 1;\n        } else if (n < 0) {\n            return -1;\n        }\n        return 0;"),
    ("gradeLabel", "int score", "if (score >= 90) {\n            return 1;\n        } else if (score >= 60) {\n            return 2;\n        }",
     "if (score >= 90) {\n            return 1;\n        } else if (score >= 60) {\n            return 2;\n        }\n        return 3;"),
    ("stockStatus", "int qty", "if (qty == 0) {\n            return 0;\n        } else if (qty < 10) {\n            return 1;\n        }",
     "if (qty == 0) {\n            return 0;\n        } else if (qty < 10) {\n            return 1;\n        }\n        return 2;"),
    ("tempAlertLevel", "int temp", "if (temp > 100) {\n            return 2;\n        } else if (temp > 80) {\n            return 1;\n        }",
     "if (temp > 100) {\n            return 2;\n        } else if (temp > 80) {\n            return 1;\n        }\n        return 0;"),
    ("batteryStatus", "int percent", "if (percent < 10) {\n            return 0;\n        } else if (percent < 50) {\n            return 1;\n        }",
     "if (percent < 10) {\n            return 0;\n        } else if (percent < 50) {\n            return 1;\n        }\n        return 2;"),
    ("shippingTier", "int weight", "if (weight > 50) {\n            return 3;\n        } else if (weight > 20) {\n            return 2;\n        }",
     "if (weight > 50) {\n            return 3;\n        } else if (weight > 20) {\n            return 2;\n        }\n        return 1;"),
    ("ageGroup", "int age", "if (age < 13) {\n            return 0;\n        } else if (age < 20) {\n            return 1;\n        }",
     "if (age < 13) {\n            return 0;\n        } else if (age < 20) {\n            return 1;\n        }\n        return 2;"),
    ("responseCodeClass", "int code", "if (code < 300) {\n            return 0;\n        } else if (code < 500) {\n            return 1;\n        }",
     "if (code < 300) {\n            return 0;\n        } else if (code < 500) {\n            return 1;\n        }\n        return 2;"),
    ("discountTier", "int total", "if (total > 100) {\n            return 20;\n        } else if (total > 50) {\n            return 10;\n        }",
     "if (total > 100) {\n            return 20;\n        } else if (total > 50) {\n            return 10;\n        }\n        return 0;"),
    ("priorityLevel", "int severity", "if (severity > 8) {\n            return 3;\n        } else if (severity > 4) {\n            return 2;\n        }",
     "if (severity > 8) {\n            return 3;\n        } else if (severity > 4) {\n            return 2;\n        }\n        return 1;"),
]

# --------------------------------------------------------------------
# Class 3: incompatible types -- assigning a String literal to an int.
# --------------------------------------------------------------------
INCOMPATIBLE_TYPES = [
    ("count", "int", '"5"', "5"),
    ("id", "int", '"42"', "42"),
    ("score", "int", '"100"', "100"),
    ("age", "int", '"30"', "30"),
    ("qty", "int", '"7"', "7"),
    ("year", "int", '"2026"', "2026"),
    ("balance", "int", '"250"', "250"),
    ("size", "int", '"12"', "12"),
    ("code", "int", '"404"', "404"),
    ("level", "int", '"1"', "1"),
]

# --------------------------------------------------------------------
# Class 4: unused import (our own detector -- javac itself never flags
# this under any -Xlint category).
# --------------------------------------------------------------------
UNUSED_IMPORT = [
    ("java.util.List", "java.util.ArrayList", "ArrayList<Integer> nums = new ArrayList<>();\n        nums.add(1);\n        nums.add(2);\n        System.out.println(nums);"),
    ("java.util.Map", "java.util.HashMap", "HashMap<String, Integer> scores = new HashMap<>();\n        scores.put(\"a\", 1);\n        System.out.println(scores);"),
    ("java.util.Set", "java.util.HashSet", "HashSet<String> tags = new HashSet<>();\n        tags.add(\"x\");\n        System.out.println(tags);"),
    ("java.io.File", "java.util.ArrayList", "ArrayList<String> names = new ArrayList<>();\n        names.add(\"Ada\");\n        System.out.println(names);"),
    ("java.util.Collections", "java.util.ArrayList", "ArrayList<Integer> vals = new ArrayList<>();\n        vals.add(3);\n        System.out.println(vals);"),
    ("java.util.Optional", "java.util.HashMap", "HashMap<String, String> config = new HashMap<>();\n        config.put(\"k\", \"v\");\n        System.out.println(config);"),
    ("java.util.Comparator", "java.util.ArrayList", "ArrayList<Integer> nums = new ArrayList<>();\n        nums.add(9);\n        System.out.println(nums);"),
    ("java.util.Arrays", "java.util.HashSet", "HashSet<Integer> seen = new HashSet<>();\n        seen.add(1);\n        System.out.println(seen);"),
    ("java.util.stream.Stream", "java.util.ArrayList", "ArrayList<Double> prices = new ArrayList<>();\n        prices.add(9.99);\n        System.out.println(prices);"),
    ("java.util.Objects", "java.util.HashMap", "HashMap<Integer, String> ids = new HashMap<>();\n        ids.put(1, \"a\");\n        System.out.println(ids);"),
]

# --------------------------------------------------------------------
# Class 5: unreported checked exception -- a method calls something that
# throws a checked exception without catching or declaring it. Each
# entry carries its own param type/name and the exception's FQN, since
# the throws clause uses the simple name and therefore needs the import.
# --------------------------------------------------------------------
UNREPORTED_EXCEPTION = [
    ("readFirstByte", "String", "path", ["java.io.FileReader"],
     "FileReader reader = new FileReader(path);\n        int b = reader.read();\n        reader.close();",
     "java.io.IOException"),
    ("parseIntStrict", "String", "text", ["java.text.ParseException"],
     "int n = Integer.parseInt(text);\n        if (n < 0) throw new ParseException(\"negative\", 0);",
     "java.text.ParseException"),
    ("sleepBriefly", "int", "millis", [],
     "Thread.sleep(millis);",
     "InterruptedException"),
    ("openUrlStream", "String", "spec", ["java.net.URL"],
     "URL url = new URL(spec);\n        url.openStream();",
     "java.io.IOException"),
    ("cloneList", "java.util.ArrayList<Integer>", "list", [],
     "java.util.ArrayList<Integer> copy = (java.util.ArrayList<Integer>) list.clone();\n        if (copy.isEmpty()) throw new CloneNotSupportedException();",
     "CloneNotSupportedException"),
]


def _write(slug: str, broken: str, fixed: str, rationale: str, confidence: float = 0.9,
           target_error_index: int | str | None = None):
    d = OUT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "broken.java").write_text(broken)
    (d / "fixed.java").write_text(fixed)

    errs = error_detector.analyze(broken, "Main.java", "java")
    if not errs:
        raise AssertionError(f"{slug}: broken.java triggers NOTHING -- bad template")

    # Some templates emit a LintWarning (e.g. [unchecked] cast,
    # [deprecation]) that sorts BEFORE the syntax error we actually want
    # the example to be about, so index 0 would target the wrong one.
    if target_error_index == "first_syntax":
        target_error_index = next((i for i, e in enumerate(errs) if e.severity == "syntax"), 0)

    meta = {"language": "java", "rationale": rationale, "confidence": confidence}
    if target_error_index is not None:
        meta["target_error_index"] = target_error_index
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return len(errs)


def main():
    n = 0
    for i, (fn, ret_type, params, broken_body, fixed_body, rationale) in enumerate(CANNOT_FIND_SYMBOL, 1):
        call_args = "5" if params.count(",") == 0 else "5, 3"
        broken = (f'public class Main {{\n    public static {ret_type} {fn}({params}) {{\n        {broken_body}\n    }}\n\n'
                   f'    public static void main(String[] args) {{\n        System.out.println({fn}({call_args}));\n    }}\n}}\n')
        fixed = (f'public class Main {{\n    public static {ret_type} {fn}({params}) {{\n        {fixed_body}\n    }}\n\n'
                  f'    public static void main(String[] args) {{\n        System.out.println({fn}({call_args}));\n    }}\n}}\n')
        _write(f"java_findsymbol_{i:02d}_{fn}", broken, fixed, rationale, target_error_index="first_syntax")
        n += 1

    for i, (fn, param, broken_body, fixed_body) in enumerate(MISSING_RETURN, 1):
        broken = (f'public class Main {{\n    public static int {fn}({param}) {{\n        {broken_body}\n    }}\n\n'
                   f'    public static void main(String[] args) {{\n        System.out.println({fn}(5));\n    }}\n}}\n')
        fixed = (f'public class Main {{\n    public static int {fn}({param}) {{\n        {fixed_body}\n    }}\n\n'
                  f'    public static void main(String[] args) {{\n        System.out.println({fn}(5));\n    }}\n}}\n')
        rationale = f"Not every path through '{fn}' returns a value -- javac rejects a non-void method that can fall off the end. Add an explicit fallback return."
        _write(f"java_missingreturn_{i:02d}_{fn}", broken, fixed, rationale, target_error_index="first_syntax")
        n += 1

    for i, (var, typ, bad_lit, good_lit) in enumerate(INCOMPATIBLE_TYPES, 1):
        broken = (f'public class Main {{\n    public static void main(String[] args) {{\n        {typ} {var} = {bad_lit};\n'
                   f'        System.out.println({var});\n    }}\n}}\n')
        fixed = (f'public class Main {{\n    public static void main(String[] args) {{\n        {typ} {var} = {good_lit};\n'
                  f'        System.out.println({var});\n    }}\n}}\n')
        rationale = f"{bad_lit} is a String literal, not an {typ} -- javac rejects the assignment. Use the {typ} literal {good_lit} instead."
        _write(f"java_incompattypes_{i:02d}_{var}", broken, fixed, rationale, target_error_index="first_syntax")
        n += 1

    for i, (unused, used, body) in enumerate(UNUSED_IMPORT, 1):
        broken = f'import {unused};\nimport {used};\n\npublic class Main {{\n    public static void main(String[] args) {{\n        {body}\n    }}\n}}\n'
        fixed = f'import {used};\n\npublic class Main {{\n    public static void main(String[] args) {{\n        {body}\n    }}\n}}\n'
        unused_simple = unused.rsplit(".", 1)[-1]
        used_simple = used.rsplit(".", 1)[-1]
        rationale = f"'{unused_simple}' is imported but the code only ever uses '{used_simple}', never '{unused_simple}' -- drop the unused import."
        _write(f"java_unusedimport_{i:02d}_{unused_simple}", broken, fixed, rationale)
        n += 1

    for i, (fn, param_type, param_name, imports, body, exc_full) in enumerate(UNREPORTED_EXCEPTION, 1):
        exc_simple = exc_full.rsplit(".", 1)[-1]
        # The throws clause uses the unqualified simple name, so its
        # package must be imported too -- java.lang exceptions (like
        # CloneNotSupportedException/InterruptedException) don't need
        # this, but java.io/java.text/java.net ones do.
        all_imports = list(imports)
        if "." in exc_full and exc_full not in all_imports:
            all_imports.append(exc_full)
        import_lines = "\n".join(f"import {imp};" for imp in all_imports)
        prefix = (import_lines + "\n\n") if import_lines else ""
        broken = (f'{prefix}public class Main {{\n    public static void {fn}({param_type} {param_name}) {{\n        {body}\n    }}\n\n'
                   f'    public static void main(String[] args) {{\n    }}\n}}\n')
        fixed = (f'{prefix}public class Main {{\n    public static void {fn}({param_type} {param_name}) throws {exc_simple} {{\n        {body}\n    }}\n\n'
                  f'    public static void main(String[] args) {{\n    }}\n}}\n')
        rationale = f"This body can throw the checked {exc_simple}, which the method neither catches nor declares -- add 'throws {exc_simple}' to the signature."
        _write(f"java_unreportedexc_{i:02d}_{fn}", broken, fixed, rationale, target_error_index="first_syntax")
        n += 1

    print(f"Generated {n} Java examples under {OUT}")


if __name__ == "__main__":
    main()

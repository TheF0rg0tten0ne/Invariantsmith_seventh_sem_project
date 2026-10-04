"""
Static completion data for the editor's suggestion popup.

Everything here is plain data (no Qt), so it is cheap to import and easy to
unit-test. An entry is a ``Completion``:

    label   what is shown in the list and matched against what you type
    kind    "snippet" | "keyword" | "func" | "type" | "module" | "word"
    body    text inserted on accept (snippet syntax, see below)
    detail  short grey hint shown at the right of the row

Snippet syntax (a deliberately tiny subset of the VS Code one):

    $1 $2 ...      tab stops, visited in order with Tab
    ${1:text}      a tab stop with default text (selected, so typing replaces it)
    $0             where the caret ends up when you press Tab past the last stop
    the same number twice = mirrored (typing in one updates the other)
    \\t            one indent level (expands to the editor's tab width)
    \\n            newline (the current line's indentation is added automatically)
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    label: str
    kind: str
    body: str
    detail: str = ""


def _kw(words: str, detail: str = "keyword") -> list[Completion]:
    return [Completion(w, "keyword", w, detail) for w in words.split()]


def _fn(names: str, detail: str = "function") -> list[Completion]:
    return [Completion(n, "func", f"{n}($1)$0", detail) for n in names.split()]


def _ty(names: str, detail: str = "type") -> list[Completion]:
    return [Completion(n, "type", n, detail) for n in names.split()]


def _mod(names: str, detail: str = "module") -> list[Completion]:
    return [Completion(n, "module", n, detail) for n in names.split()]


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
_PY_SNIPPETS = [
    Completion("def", "snippet", "def ${1:name}(${2:args}):\n\t${0:pass}", "function"),
    Completion("class", "snippet", "class ${1:Name}:\n\tdef __init__(self${2}):\n\t\t${0:pass}", "class with __init__"),
    Completion("if", "snippet", "if ${1:condition}:\n\t${0:pass}", "if statement"),
    Completion("elif", "snippet", "elif ${1:condition}:\n\t${0:pass}", "elif branch"),
    Completion("else", "snippet", "else:\n\t${0:pass}", "else branch"),
    Completion("for", "snippet", "for ${1:item} in ${2:items}:\n\t${0:pass}", "for loop"),
    Completion("fori", "snippet", "for ${1:i} in range(${2:n}):\n\t${0:pass}", "for i in range"),
    Completion("while", "snippet", "while ${1:condition}:\n\t${0:pass}", "while loop"),
    Completion("try", "snippet", "try:\n\t${1:pass}\nexcept ${2:Exception} as ${3:e}:\n\t${0:raise}", "try / except"),
    Completion("finally", "snippet", "finally:\n\t${0:pass}", "finally block"),
    Completion("with", "snippet", "with ${1:open(path)} as ${2:f}:\n\t${0:pass}", "with statement"),
    Completion("withopen", "snippet", "with open(${1:path}, \"${2:r}\") as ${3:f}:\n\t${0:pass}", "open a file"),
    Completion("lambda", "snippet", "lambda ${1:x}: ${0:x}", "lambda"),
    Completion("main", "snippet", "def main():\n\t${0:pass}\n\n\nif __name__ == \"__main__\":\n\tmain()", "main() + entry guard"),
    Completion("ifmain", "snippet", "if __name__ == \"__main__\":\n\t${0:main()}", "entry-point guard"),
    Completion("print", "snippet", "print(${1})$0", "print()"),
    Completion("printf", "snippet", "print(f\"${1}\")$0", "print an f-string"),
    Completion("readint", "snippet", "${1:n} = int(input(${2}))$0", "read an int"),
    Completion("readints", "snippet", "${1:nums} = list(map(int, input().split()))$0", "read a list of ints"),
    Completion("import", "snippet", "import ${0}", "import"),
    Completion("from", "snippet", "from ${1:module} import ${0:name}", "from … import …"),
    Completion("dataclass", "snippet", "@dataclass\nclass ${1:Name}:\n\t${0:field: int}", "dataclass"),
    Completion("listcomp", "snippet", "[${1:x} for ${2:x} in ${3:items}${4}]$0", "list comprehension"),
    Completion("match", "snippet", "match ${1:value}:\n\tcase ${2:pattern}:\n\t\t${0:pass}", "match statement"),
]

_PY_KEYWORDS = _kw(
    "and as assert async await break continue del except global in is nonlocal not or "
    "pass raise return yield None True False self"
)

_PY_BUILTINS = _fn(
    "abs all any bin bool bytes callable chr dict divmod enumerate filter float format frozenset "
    "getattr hasattr hash hex id input int isinstance issubclass iter len list map max min next "
    "object oct open ord pow range repr reversed round set setattr slice sorted str sum super "
    "tuple type vars zip",
    "builtin",
)

_PY_MODULES = _mod(
    "abc argparse array asyncio bisect collections copy csv ctypes dataclasses datetime decimal "
    "enum functools glob hashlib heapq io itertools json logging math os pathlib pickle queue "
    "random re shutil socket sqlite3 statistics string struct subprocess sys tempfile textwrap "
    "threading time traceback typing unittest urllib uuid warnings"
)

# ---------------------------------------------------------------------------
# C
# ---------------------------------------------------------------------------
_C_HEADERS = (
    "assert.h ctype.h errno.h float.h inttypes.h limits.h locale.h math.h setjmp.h signal.h "
    "stdarg.h stdbool.h stddef.h stdint.h stdio.h stdlib.h string.h time.h unistd.h"
).split()

_C_SNIPPETS = [
    Completion("main", "snippet", "int main(void) {\n\t$0\n\treturn 0;\n}", "main()"),
    Completion("maina", "snippet", "int main(int argc, char *argv[]) {\n\t$0\n\treturn 0;\n}", "main(argc, argv)"),
    Completion("if", "snippet", "if (${1:condition}) {\n\t$0\n}", "if statement"),
    Completion("ifelse", "snippet", "if (${1:condition}) {\n\t${2}\n} else {\n\t${0}\n}", "if / else"),
    Completion("else", "snippet", "else {\n\t$0\n}", "else block"),
    Completion("elseif", "snippet", "else if (${1:condition}) {\n\t$0\n}", "else if"),
    Completion("for", "snippet", "for (int ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t$0\n}", "for loop"),
    Completion("fori", "snippet", "for (int ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t$0\n}", "for loop"),
    Completion("forr", "snippet", "for (int ${1:i} = ${2:n} - 1; ${1:i} >= 0; ${1:i}--) {\n\t$0\n}", "reverse for loop"),
    Completion("while", "snippet", "while (${1:condition}) {\n\t$0\n}", "while loop"),
    Completion("do", "snippet", "do {\n\t$0\n} while (${1:condition});", "do / while"),
    Completion("switch", "snippet",
               "switch (${1:value}) {\ncase ${2:0}:\n\t$0\n\tbreak;\ndefault:\n\tbreak;\n}", "switch"),
    Completion("struct", "snippet", "struct ${1:Name} {\n\t$0\n};", "struct"),
    Completion("typedef", "snippet", "typedef struct {\n\t$0\n} ${1:Name};", "typedef struct"),
    Completion("enum", "snippet", "enum ${1:Name} {\n\t$0\n};", "enum"),
    Completion("func", "snippet", "${1:int} ${2:name}(${3:void}) {\n\t$0\n}", "function"),
    Completion("printf", "snippet", "printf(\"${1}\\n\"$2);$0", "printf"),
    Completion("scanf", "snippet", "scanf(\"${1:%d}\", &${2:n});$0", "scanf"),
    Completion("scanfi", "snippet", "int ${1:n};\nscanf(\"%d\", &${1:n});$0", "declare + scan an int"),
    Completion("fgets", "snippet", "fgets(${1:buf}, sizeof(${1:buf}), stdin);$0", "fgets from stdin"),
    Completion("puts", "snippet", "puts(\"${1}\");$0", "puts"),
    Completion("fprintf", "snippet", "fprintf(${1:stderr}, \"${2}\\n\"$3);$0", "fprintf"),
    Completion("malloc", "snippet", "${1:int} *${2:p} = malloc(${3:n} * sizeof(${1:int}));\nif (${2:p} == NULL) {\n\t$0\n}",
               "malloc + NULL check"),
    Completion("free", "snippet", "free(${1:p});$0", "free"),
    Completion("fopen", "snippet",
               "FILE *${1:fp} = fopen(\"${2:file.txt}\", \"${3:r}\");\nif (${1:fp} == NULL) {\n\t$0\n}",
               "fopen + NULL check"),
    Completion("fclose", "snippet", "fclose(${1:fp});$0", "fclose"),
    Completion("ifndef", "snippet", "#ifndef ${1:HEADER_H}\n#define ${1:HEADER_H}\n\n$0\n\n#endif", "include guard"),
    Completion("#define", "snippet", "#define ${1:NAME} ${0:value}", "macro"),
    Completion("#ifdef", "snippet", "#ifdef ${1:NAME}\n$0\n#endif", "#ifdef"),
    Completion("#ifndef", "snippet", "#ifndef ${1:NAME}\n$0\n#endif", "#ifndef"),
    Completion("#include", "snippet", "#include <${0:stdio.h}>", "#include <…>"),
]

_C_KEYWORDS = _kw(
    "auto break case char const continue default do double else enum extern float for goto if "
    "inline int long register restrict return short signed sizeof static struct switch typedef "
    "union unsigned void volatile while NULL true false"
)

_C_TYPES = _ty(
    "size_t ssize_t FILE int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t bool "
    "ptrdiff_t time_t clock_t va_list"
)

_C_FUNCS = (
    _fn("strlen strcmp strncmp strcpy strncpy strcat strncat strchr strrchr strstr strtok strdup memcpy memmove memset memcmp",
        "string.h")
    + _fn("malloc calloc realloc free atoi atol atof strtol strtod rand srand exit abort qsort bsearch abs labs getenv system",
          "stdlib.h")
    + _fn("sqrt pow sin cos tan asin acos atan atan2 exp log log10 ceil floor fabs fmod round trunc hypot", "math.h")
    + _fn("isalpha isdigit isalnum isspace isupper islower ispunct toupper tolower", "ctype.h")
    + _fn("fopen fclose fread fwrite fgets fputs fgetc fputc fseek ftell rewind fflush feof ferror remove rename perror "
          "getchar putchar puts gets_s sscanf fscanf vprintf", "stdio.h")
    + _fn("time clock difftime", "time.h")
    + _fn("assert", "assert.h")
)

# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------
_JAVA_SNIPPETS = [
    Completion("main", "snippet", "public static void main(String[] args) {\n\t$0\n}", "main method"),
    Completion("psvm", "snippet", "public static void main(String[] args) {\n\t$0\n}", "main method"),
    Completion("sout", "snippet", "System.out.println(${1});$0", "System.out.println"),
    Completion("soutp", "snippet", "System.out.print(${1});$0", "System.out.print"),
    Completion("souf", "snippet", "System.out.printf(\"${1}%n\"$2);$0", "System.out.printf"),
    Completion("serr", "snippet", "System.err.println(${1});$0", "System.err.println"),
    Completion("if", "snippet", "if (${1:condition}) {\n\t$0\n}", "if statement"),
    Completion("ifelse", "snippet", "if (${1:condition}) {\n\t${2}\n} else {\n\t${0}\n}", "if / else"),
    Completion("else", "snippet", "else {\n\t$0\n}", "else block"),
    Completion("elseif", "snippet", "else if (${1:condition}) {\n\t$0\n}", "else if"),
    Completion("for", "snippet", "for (int ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t$0\n}", "for loop"),
    Completion("fori", "snippet", "for (int ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t$0\n}", "for loop"),
    Completion("forr", "snippet", "for (int ${1:i} = ${2:n} - 1; ${1:i} >= 0; ${1:i}--) {\n\t$0\n}", "reverse for loop"),
    Completion("foreach", "snippet", "for (${1:String} ${2:item} : ${3:items}) {\n\t$0\n}", "enhanced for"),
    Completion("while", "snippet", "while (${1:condition}) {\n\t$0\n}", "while loop"),
    Completion("do", "snippet", "do {\n\t$0\n} while (${1:condition});", "do / while"),
    Completion("switch", "snippet",
               "switch (${1:value}) {\n\tcase ${2:0}:\n\t\t$0\n\t\tbreak;\n\tdefault:\n\t\tbreak;\n}", "switch"),
    Completion("try", "snippet", "try {\n\t$1\n} catch (${2:Exception} ${3:e}) {\n\t${0:e.printStackTrace();}\n}", "try / catch"),
    Completion("catch", "snippet", "catch (${1:Exception} ${2:e}) {\n\t$0\n}", "catch block"),
    Completion("finally", "snippet", "finally {\n\t$0\n}", "finally block"),
    Completion("class", "snippet", "public class ${1:Main} {\n\t$0\n}", "class"),
    Completion("interface", "snippet", "public interface ${1:Name} {\n\t$0\n}", "interface"),
    Completion("enum", "snippet", "public enum ${1:Name} {\n\t$0\n}", "enum"),
    Completion("method", "snippet", "public ${1:void} ${2:name}(${3}) {\n\t$0\n}", "method"),
    Completion("psf", "snippet", "public static final ${1:int} ${2:NAME} = ${0:0};", "constant"),
    Completion("scanner", "snippet", "Scanner ${1:sc} = new Scanner(System.in);$0", "Scanner on stdin"),
    Completion("readint", "snippet", "Scanner ${1:sc} = new Scanner(System.in);\nint ${2:n} = ${1:sc}.nextInt();$0",
               "read an int"),
    Completion("list", "snippet", "List<${1:Integer}> ${2:list} = new ArrayList<>();$0", "ArrayList"),
    Completion("map", "snippet", "Map<${1:String}, ${2:Integer}> ${3:map} = new HashMap<>();$0", "HashMap"),
    Completion("set", "snippet", "Set<${1:Integer}> ${2:set} = new HashSet<>();$0", "HashSet"),
    Completion("sb", "snippet", "StringBuilder ${1:sb} = new StringBuilder();$0", "StringBuilder"),
    Completion("new", "snippet", "new ${1:Type}(${2})$0", "new object"),
]

_JAVA_KEYWORDS = _kw(
    "abstract assert boolean break byte case catch char class const continue default do double "
    "else enum extends final finally float for if implements import instanceof int interface long "
    "native new null package private protected public return short static strictfp super switch "
    "synchronized this throw throws transient true false try var void volatile while record"
)

_JAVA_TYPES = _ty(
    "String Integer Long Double Float Boolean Character Byte Short Object Number Math System "
    "StringBuilder StringBuffer List ArrayList LinkedList Map HashMap TreeMap LinkedHashMap Set "
    "HashSet TreeSet Queue Deque ArrayDeque PriorityQueue Stack Arrays Collections Optional "
    "Scanner Random Iterator Comparator Comparable Exception RuntimeException IOException "
    "IllegalArgumentException IllegalStateException NullPointerException BufferedReader "
    "InputStreamReader File Files Path Thread Runnable LocalDate LocalDateTime Instant Duration",
    "class",
)

_JAVA_IMPORTS = (
    "java.util.* java.util.Scanner java.util.ArrayList java.util.List java.util.Map java.util.HashMap "
    "java.util.Set java.util.HashSet java.util.Arrays java.util.Collections java.util.Random "
    "java.util.Optional java.util.Queue java.util.Deque java.util.ArrayDeque java.util.PriorityQueue "
    "java.util.stream.* java.util.function.* java.io.* java.io.BufferedReader java.io.InputStreamReader "
    "java.io.IOException java.io.File java.nio.file.* java.time.* java.math.BigInteger java.math.BigDecimal"
).split()

# ---------------------------------------------------------------------------
# Public tables
# ---------------------------------------------------------------------------
# Order matters only as a tie-break: snippets override a keyword/function with
# the same label (so "for" offers the loop template, not the bare word).
_TABLE = {
    "python": _PY_SNIPPETS + _PY_KEYWORDS + _PY_BUILTINS,
    "c": _C_SNIPPETS + _C_KEYWORDS + _C_TYPES + _C_FUNCS,
    "java": _JAVA_SNIPPETS + _JAVA_KEYWORDS + _JAVA_TYPES,
}

MODULES = {
    "python": [m.label for m in _PY_MODULES],
    "c": _C_HEADERS,
    "java": _JAVA_IMPORTS,
}

# Identifier characters per language (C also treats a leading '#' as part of a
# word so "#inc" completes the directive).
LANGUAGES = tuple(_TABLE)


def completions_for(language: str) -> list[Completion]:
    """Deduplicated completion list; the first entry for a label wins."""
    seen, out = set(), []
    for c in _TABLE.get(language, []):
        if c.label in seen:
            continue
        seen.add(c.label)
        out.append(c)
    return out


# Header-style one-liners offered when you type "#include": expanded here so
# the user can pick `#include <stdio.h>` directly rather than via two steps.
def c_include_lines() -> list[Completion]:
    return [Completion(f"#include <{h}>", "snippet", f"#include <{h}>", "header") for h in _C_HEADERS]


# ---------------------------------------------------------------------------
# Member completion (after a dot)
# ---------------------------------------------------------------------------
# We have no type information, so "x." offers the commonly-used methods of the
# language's everyday types ("*"); well-known qualifiers (Math., os.path., ...)
# get their exact member list. A leading "~" marks a property/constant that is
# inserted without parentheses.
def _members(spec: str, detail: str) -> list[Completion]:
    out = []
    for n in spec.split():
        if n.startswith("~"):
            out.append(Completion(n[1:], "member", n[1:], detail))
        else:
            out.append(Completion(n, "member", f"{n}($1)$0", detail))
    return out


MEMBERS: dict[str, dict[str, list[Completion]]] = {
    "python": {
        "*": _members(
            "append extend insert remove pop clear index count sort reverse copy keys values items get update "
            "setdefault add discard union intersection difference join split rsplit strip lstrip rstrip replace "
            "find rfind startswith endswith upper lower title capitalize format isdigit isalpha isalnum isspace "
            "splitlines encode decode zfill center ljust rjust partition", "method"),
        "math": _members("sqrt floor ceil pow log log2 log10 sin cos tan atan2 gcd lcm factorial fabs isclose "
                         "hypot radians degrees comb perm ~pi ~e ~inf ~tau", "math"),
        "os": _members("getcwd listdir makedirs mkdir remove rename walk system getenv ~environ ~path ~sep ~name",
                       "os"),
        "os.path": _members("join exists isfile isdir basename dirname splitext abspath getsize expanduser", "os.path"),
        "sys": _members("exit ~argv ~stdin ~stdout ~stderr ~path ~platform ~version ~maxsize", "sys"),
        "random": _members("random randint randrange choice choices shuffle sample seed uniform gauss", "random"),
        "time": _members("time sleep perf_counter monotonic strftime localtime", "time"),
        "json": _members("dumps loads dump load", "json"),
        "re": _members("match search fullmatch findall finditer sub split compile escape", "re"),
        "collections": _members("Counter defaultdict deque OrderedDict namedtuple ChainMap", "collections"),
        "itertools": _members("product permutations combinations accumulate chain count cycle groupby islice "
                              "zip_longest repeat", "itertools"),
        "datetime": _members("datetime date time timedelta timezone", "datetime"),
        "heapq": _members("heappush heappop heapify nlargest nsmallest heapreplace", "heapq"),
        "string": _members("~ascii_letters ~ascii_lowercase ~ascii_uppercase ~digits ~punctuation", "string"),
    },
    "java": {
        "*": _members(
            "add get set remove size isEmpty contains clear length charAt substring indexOf lastIndexOf equals "
            "equalsIgnoreCase compareTo toString toCharArray split trim strip toUpperCase toLowerCase startsWith "
            "endsWith replace isBlank append insert reverse put containsKey getOrDefault keySet values entrySet "
            "push pop peek poll offer addAll forEach stream nextInt nextLine next hasNext hasNextInt close "
            "hashCode getClass", "method"),
        "System": _members("~out ~err ~in currentTimeMillis nanoTime exit arraycopy getProperty lineSeparator",
                           "System"),
        "System.out": _members("println print printf format flush", "PrintStream"),
        "System.err": _members("println print printf format flush", "PrintStream"),
        "Math": _members("abs max min pow sqrt cbrt floor ceil round random sin cos tan log log10 exp hypot "
                         "floorMod floorDiv signum ~PI ~E", "Math"),
        "Integer": _members("parseInt valueOf toString compare toBinaryString toHexString sum max min "
                            "~MAX_VALUE ~MIN_VALUE", "Integer"),
        "Long": _members("parseLong valueOf toString compare ~MAX_VALUE ~MIN_VALUE", "Long"),
        "Double": _members("parseDouble valueOf toString compare isNaN ~MAX_VALUE ~MIN_VALUE", "Double"),
        "Character": _members("isDigit isLetter isLetterOrDigit isUpperCase isLowerCase isWhitespace toUpperCase "
                              "toLowerCase getNumericValue", "Character"),
        "String": _members("valueOf format join copyValueOf", "String"),
        "Arrays": _members("sort fill toString deepToString asList copyOf copyOfRange stream equals binarySearch",
                           "Arrays"),
        "Collections": _members("sort reverse shuffle max min swap unmodifiableList emptyList frequency", "Collections"),
        "List": _members("of copyOf", "List"),
        "Map": _members("of entry copyOf", "Map"),
        "Objects": _members("equals hash hashCode requireNonNull isNull nonNull toString", "Objects"),
    },
}


def member_completions(language: str, qualifier: str) -> list[Completion]:
    table = MEMBERS.get(language, {})
    return table.get(qualifier) or table.get("*", [])

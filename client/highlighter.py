"""
Tree-sitter based syntax highlighting, now for Python, C, and Java.

We reparse the whole buffer on each debounced change (cheap for typical
file sizes; tree-sitter's incremental parsing is a later optimization,
not needed here) and walk the resulting tree to collect
(start_offset, end_offset, category) spans. QSyntaxHighlighter then looks
up which spans intersect each block as Qt asks it to paint.

Categories map directly onto the theme token names in themes/*.json --
see theme.py for how colors get pulled in. The three grammars have
different node-type vocabularies, so each language gets its own small
config (keyword set, literal node types, and where to find
function/class names) rather than one universal walk -- trying to force
Python/C/Java into identical tree shapes would be more fragile than just
describing each one directly.
"""
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont

from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_c as tsc
import tree_sitter_java as tsjava


# ---------------------------------------------------------------------
# Per-language configuration
# ---------------------------------------------------------------------

_PY_KEYWORDS = {
    "def", "class", "return", "if", "elif", "else", "for", "while", "break",
    "continue", "pass", "import", "from", "as", "with", "try", "except",
    "finally", "raise", "in", "is", "not", "and", "or", "lambda", "yield",
    "global", "nonlocal", "assert", "del", "async", "await", "None", "True",
    "False",
}
_PY_NODE_CATEGORY = {
    "string": "string", "string_start": "string", "string_content": "string",
    "string_end": "string", "integer": "number", "float": "number",
    "comment": "comment",
}

_C_KEYWORDS = {
    "if", "else", "for", "while", "do", "switch", "case", "default", "break",
    "continue", "return", "goto", "struct", "union", "enum", "typedef",
    "static", "const", "sizeof", "extern", "register", "volatile", "auto",
    "inline", "restrict", "void", "signed", "unsigned",
}
_C_NODE_CATEGORY = {
    "string_literal": "string", "char_literal": "string",
    "system_lib_string": "string", "number_literal": "number",
    "comment": "comment", "primitive_type": "keyword",
}

_JAVA_KEYWORDS = {
    "public", "private", "protected", "static", "final", "abstract", "class",
    "interface", "enum", "extends", "implements", "new", "return", "if",
    "else", "for", "while", "do", "switch", "case", "default", "break",
    "continue", "try", "catch", "finally", "throw", "throws", "import",
    "package", "this", "super", "instanceof", "void", "synchronized",
    "transient", "native", "strictfp", "volatile", "assert", "null", "true",
    "false", "int", "boolean", "double", "float", "long", "short", "byte",
    "char",
}
_JAVA_NODE_CATEGORY = {
    "string_literal": "string", "character_literal": "string",
    "decimal_integer_literal": "number", "hex_integer_literal": "number",
    "decimal_floating_point_literal": "number", "octal_integer_literal": "number",
    "line_comment": "comment", "block_comment": "comment",
}


def _py_definitions(node, out: list):
    if node.type == "function_definition":
        n = node.child_by_field_name("name")
        if n:
            out.append((n.start_byte, n.end_byte, "function"))
    elif node.type == "class_definition":
        n = node.child_by_field_name("name")
        if n:
            out.append((n.start_byte, n.end_byte, "class"))


def _innermost_identifier(node):
    """C function declarators nest ((*name)(args)) style wrappers around
    the identifier -- walk down 'declarator' fields until there's nothing
    left to descend into."""
    while node is not None and node.type != "identifier":
        nxt = node.child_by_field_name("declarator")
        if nxt is None:
            return None
        node = nxt
    return node


def _c_definitions(node, out: list):
    if node.type == "function_definition":
        declarator = node.child_by_field_name("declarator")
        ident = _innermost_identifier(declarator) if declarator else None
        if ident:
            out.append((ident.start_byte, ident.end_byte, "function"))
    elif node.type.startswith("preproc_"):
        out.append((node.start_byte, node.end_byte, "keyword"))


def _java_definitions(node, out: list):
    if node.type in ("method_declaration", "constructor_declaration"):
        n = node.child_by_field_name("name")
        if n:
            out.append((n.start_byte, n.end_byte, "function"))
    elif node.type in ("class_declaration", "interface_declaration", "enum_declaration"):
        n = node.child_by_field_name("name")
        if n:
            out.append((n.start_byte, n.end_byte, "class"))


_CONFIGS = {
    "python": dict(
        ts_language=Language(tspython.language()),
        keywords=_PY_KEYWORDS,
        node_category=_PY_NODE_CATEGORY,
        definitions=_py_definitions,
    ),
    "c": dict(
        ts_language=Language(tsc.language()),
        keywords=_C_KEYWORDS,
        node_category=_C_NODE_CATEGORY,
        definitions=_c_definitions,
    ),
    "java": dict(
        ts_language=Language(tsjava.language()),
        keywords=_JAVA_KEYWORDS,
        node_category=_JAVA_NODE_CATEGORY,
        definitions=_java_definitions,
    ),
}

CATEGORIES = ("keyword", "string", "number", "comment", "function", "class", "variable")


class TreeSitterHighlighter(QSyntaxHighlighter):
    def __init__(self, document, theme_colors: dict, language: str = "python"):
        super().__init__(document)
        self._spans: list[tuple[int, int, str]] = []  # (start, end, category)
        self._language = language if language in _CONFIGS else "python"
        self._parser = Parser(_CONFIGS[self._language]["ts_language"])
        self.set_theme(theme_colors)

    def set_language(self, language: str):
        """Switch grammars (e.g. the user picked a different language from
        the toolbar, or auto-detect changed its mind). Caller is expected
        to follow this with reparse() -- this only swaps the parser."""
        if language not in _CONFIGS or language == self._language:
            return
        self._language = language
        self._parser = Parser(_CONFIGS[self._language]["ts_language"])

    def set_theme(self, theme_colors: dict):
        self._formats: dict[str, QTextCharFormat] = {}
        for category in CATEGORIES:
            fmt = QTextCharFormat()
            color = theme_colors.get(category)
            if color:
                fmt.setForeground(QColor(color))
            if category == "comment":
                fmt.setFontItalic(True)
            if category == "keyword":
                fmt.setFontWeight(QFont.Weight.Medium)
            self._formats[category] = fmt
        self.rehighlight()

    def reparse(self, source_text: str):
        """Call this after every debounced text change, before rehighlight()."""
        source_bytes = source_text.encode("utf-8")
        tree = self._parser.parse(source_bytes)
        self._spans = []
        cfg = _CONFIGS[self._language]
        self._walk(tree.root_node, cfg)
        # NOTE: MVP assumption -- byte offsets == char offsets. Holds for
        # ASCII source. Non-ASCII identifiers/strings will drift; fixing
        # this means tracking a byte->char offset map, left as a known
        # limitation for v2.
        self.rehighlight()

    def _walk(self, node, cfg):
        node_type = node.type
        node_category = cfg["node_category"]
        keywords = cfg["keywords"]

        if node_type in node_category:
            self._spans.append((node.start_byte, node.end_byte, node_category[node_type]))
        elif node_type in keywords and not node.child_count:
            self._spans.append((node.start_byte, node.end_byte, "keyword"))
        else:
            cfg["definitions"](node, self._spans)

        for child in node.children:
            self._walk(child, cfg)

    def highlightBlock(self, text: str):
        block_start = self.currentBlock().position()
        block_end = block_start + len(text)

        for start, end, category in self._spans:
            if end <= block_start or start >= block_end:
                continue
            fmt = self._formats.get(category)
            if not fmt:
                continue
            local_start = max(start, block_start) - block_start
            local_end = min(end, block_end) - block_start
            if local_end > local_start:
                self.setFormat(local_start, local_end - local_start, fmt)

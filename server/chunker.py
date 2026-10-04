"""
Scope-finding for chunked fixes: given a (possibly large) file, a
language, and the line an error was reported on, find a *small*, roughly
self-contained span of the file to send to the model -- instead of the
whole file.

Why this exists: suggest_fix() used to always send the entire file and ask
for the entire file back. That's fine for a 20-line file, but on a chonky
one it means (a) a bigger prompt+output budget (already handled by
fixer.py's dynamic budget) and, more importantly, (b) the model reasoning
over hundreds of lines it doesn't need to touch at all -- which is where a
1.5B model's ACCURACY falls apart, not just its speed. A 250-line C file
with one missing brace produced a confidently-wrong "fix" whose rationale
described a completely different, nonexistent bug elsewhere in the file,
while the same class of bug in a ~20-line snippet was fixed correctly and
verifiably in one shot. Shrinking what the model has to look at directly
targets that accuracy gap.

This module answers one question: "given the error is on line N, what's
the smallest reasonable chunk of the file a fix should be scoped to?" It
does NOT try to be a real parser -- same "cheap heuristic, not a compiler
frontend" philosophy as error_detector.py's brace-balance checks -- and it
degrades gracefully (falls back to a plain line-window) rather than ever
raising on malformed input, since malformed input is exactly the case
this is often invoked for (a fix is being requested BECAUSE the file is
broken; the scope-finder can't assume well-formed structure).
"""
import ast
from typing import Optional

from . import languages


def find_scope(code: str, language: str, error_line: Optional[int],
                min_lines: int = 12, max_lines: int = 80) -> Optional[tuple[int, int]]:
    """Returns (start_line, end_line), 1-indexed inclusive, sized between
    min_lines and max_lines where possible. Returns None if no error line
    was given at all -- the caller should fall back to full-file mode in
    that case, since there's nothing to scope around."""
    if error_line is None:
        return None
    lines = code.split("\n")
    n = len(lines)
    if n == 0:
        return None
    error_line = max(1, min(error_line, n))

    if language == languages.PYTHON.id:
        scope = _python_scope(code, error_line)
        if scope:
            return _pad_to_min(scope, n, min_lines, max_lines)
        return _blank_line_window(lines, error_line, min_lines, max_lines)

    # C / Java / anything else brace-delimited.
    segments = _toplevel_segments(lines)
    scope = _merge_to_min(segments, error_line, min_lines, max_lines) if segments else None
    if scope:
        return scope
    return _blank_line_window(lines, error_line, min_lines, max_lines)


def _pad_to_min(scope: tuple[int, int], n: int, min_lines: int, max_lines: int) -> tuple[int, int]:
    """Grow a scope that came back smaller than min_lines (e.g. a
    one-line Python statement) by pulling in file context around it,
    without exceeding max_lines."""
    start, end = scope
    while (end - start + 1) < min_lines and (start > 1 or end < n):
        if start > 1:
            start -= 1
        if (end - start + 1) < min_lines and end < n:
            end += 1
        if (end - start + 1) >= max_lines:
            break
    end = min(end, start + max_lines - 1, n)
    return start, end


def _python_scope(code: str, error_line: int) -> Optional[tuple[int, int]]:
    """The enclosing top-level statement/def/class span, via a real AST --
    far more precise than any heuristic when the file actually parses.
    Returns None if it doesn't parse (a syntax error is exactly the kind
    of bug this tool exists to fix, so this is a common, expected case,
    not an edge case) -- the caller falls back to a line-window."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    best = None
    for node in tree.body:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None) or start
        if start is None:
            continue
        if start <= error_line <= end:
            return start, end
        # error_line can land in a gap no top-level node covers (blank
        # lines / comments between statements, or past the last one) --
        # keep track of the nearest node so we still return something
        # reasonable instead of nothing.
        if best is None or abs(start - error_line) < abs(best[0] - error_line):
            best = (start, end)
    return best


def _toplevel_segments(lines: list[str]) -> list[tuple[int, int]]:
    """Split the file into a gap-free sequence of 'top-level unit'
    candidates: each segment ends where brace-depth returns to 0 at a
    natural boundary (a top-level ';', a top-level '}', a preprocessor
    directive line, or a blank line).

    Deliberately crude, and deliberately fragments on badly broken input
    rather than trying to be clever about it -- e.g. a struct missing its
    opening '{' produces several small 1-2 line segments instead of one
    clean "struct" segment, because each field line at depth 0 ends with
    ';' and looks like its own top-level statement. That fragmentation is
    exactly what _merge_to_min below is for: it merges neighboring small
    segments back up to a workable size, which naturally re-assembles a
    broken block like that into one coherent chunk without this function
    needing to understand WHY it was broken.
    """
    n = len(lines)
    segments: list[tuple[int, int]] = []
    seg_start = 1
    depth = 0
    in_string: Optional[str] = None
    in_block_comment = False
    for lineno in range(1, n + 1):
        text = lines[lineno - 1]
        i, L = 0, len(text)
        while i < L:
            c = text[i]
            if in_block_comment:
                if c == "*" and i + 1 < L and text[i + 1] == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            if in_string:
                if c == "\\":
                    i += 2
                    continue
                if c == in_string:
                    in_string = None
                i += 1
                continue
            if c in ('"', "'"):
                in_string = c
                i += 1
                continue
            if c == "/" and i + 1 < L and text[i + 1] == "/":
                break  # rest of line is a line comment
            if c == "/" and i + 1 < L and text[i + 1] == "*":
                in_block_comment = True
                i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth = max(0, depth - 1)  # clamp: never go negative on broken input
            i += 1

        stripped = text.strip()
        at_top = depth == 0
        closes_here = at_top and (
            stripped == ""
            or stripped.startswith("#")
            or stripped.endswith(";")
            or stripped.endswith("}")
            or stripped.endswith("*/")
            or lineno == n
        )
        if closes_here:
            segments.append((seg_start, lineno))
            seg_start = lineno + 1
    if seg_start <= n:
        segments.append((seg_start, n))
    return segments


def _merge_to_min(segments: list[tuple[int, int]], error_line: int,
                   min_lines: int, max_lines: int) -> Optional[tuple[int, int]]:
    """Starting from the segment containing error_line, merge in
    neighboring segments (whichever side keeps error_line closer to the
    center of the growing scope) until the scope reaches min_lines,
    capped at max_lines. This is what turns a fragmented broken struct
    (several 1-2 line segments) back into one sendable chunk, and what
    leaves an already-well-formed function (one segment, already big
    enough) untouched."""
    idx = next((i for i, (s, e) in enumerate(segments) if s <= error_line <= e), None)
    if idx is None:
        return None

    lo = hi = idx
    start, end = segments[idx]
    while (end - start + 1) < min_lines and (lo > 0 or hi < len(segments) - 1):
        can_left = lo > 0
        can_right = hi < len(segments) - 1
        if can_left and (not can_right or
                          (error_line - segments[lo - 1][0]) <= (segments[hi + 1][1] - error_line)):
            lo -= 1
            start = segments[lo][0]
        elif can_right:
            hi += 1
            end = segments[hi][1]
        else:
            break
        if end - start + 1 >= max_lines:
            break
    return start, min(end, start + max_lines - 1)


def _blank_line_window(lines: list[str], error_line: int,
                        min_lines: int, max_lines: int) -> tuple[int, int]:
    """Last-resort fallback when neither a real parse (Python) nor
    brace-depth segmentation (C/Java) produced a usable scope: grow a
    window around error_line, snapping outward to blank lines where
    possible, capped at max_lines. Always returns something -- this is
    the floor under every other strategy here."""
    n = len(lines)
    start = end = error_line
    while end - start + 1 < max_lines:
        have_min = (end - start + 1) >= min_lines
        up_blank = start <= 1 or lines[start - 2].strip() == ""
        down_blank = end >= n or lines[end].strip() == ""
        if have_min and up_blank and down_blank:
            break
        if start > 1 and not up_blank:
            start -= 1
        elif end < n and not down_blank:
            end += 1
        elif start > 1:
            start -= 1
        elif end < n:
            end += 1
        else:
            break
    return start, end

"""
Unified diff helpers.

The model is prompted to emit a unified diff rather than a full-file
rewrite. This module generates diffs for fallback/testing and applies
model-produced diffs to a buffer safely.
"""
import difflib
import re


def is_valid_unified_diff(diff_text: str) -> bool:
    """
    Structural sanity check: does this actually look like a unified diff,
    or is it just code the model echoed back?

    We check for a real hunk header (@@ -a,b +c,d @@) plus at least one
    added or removed line. This catches the common small-model failure
    mode of returning the original/rewritten code with no diff markers.
    """
    if not re.search(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", diff_text, re.MULTILINE):
        return False
    has_change_line = any(
        line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        for line in diff_text.splitlines()
    )
    return has_change_line


def _ensure_final_newline(lines: list[str]) -> list[str]:
    """Give the last line a terminator so difflib emits well-formed rows.

    Without this, a buffer that ends in `}` (no newline) diffed against a
    model output ending in `}\\n` produced the body row `-}+}\\n`: the removed
    and added lines were glued together, so apply_diff could never match it
    and every Apply came back as a 409 stale_diff.
    """
    if lines and not lines[-1].endswith("\n"):
        lines = lines[:-1] + [lines[-1] + "\n"]
    return lines


def _eq_ignoring_final_newline(a: str, b: str) -> bool:
    """Compare two lines, treating a missing trailing newline as equal to one.
    Only the final EOL is ignored; every other byte (CRLF, tabs, trailing
    spaces) still has to match exactly."""
    if a.endswith("\n"):
        a = a[:-1]
    if b.endswith("\n"):
        b = b[:-1]
    return a == b


def make_diff(original: str, fixed: str, filename: str = "buffer.py") -> str:
    original_lines = _ensure_final_newline(original.splitlines(keepends=True))
    fixed_lines = _ensure_final_newline(fixed.splitlines(keepends=True))
    diff = difflib.unified_diff(
        original_lines, fixed_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}",
    )
    return "".join(diff)


def apply_diff(original: str, diff_text: str) -> str:
    """
    Apply a unified diff to `original`. Minimal, dependency-free patch
    applier — sufficient for single-hunk-per-file, LLM-generated diffs.
    For multi-file / fuzzy patches, shell out to `patch` or use `unidiff`.
    """
    original_lines = original.splitlines(keepends=True)
    result = list(original_lines)

    hunks = _parse_hunks(diff_text, original_lines)
    # Apply hunks bottom-to-top so earlier line offsets stay valid.
    for hunk in sorted(hunks, key=lambda h: h["orig_start"], reverse=True):
        start = hunk["orig_start"] - 1
        end = start + hunk["orig_len"]
        # Inserting after a last line that has no newline (buffer without a
        # trailing EOL) would glue the new text onto it -- terminate it first.
        if hunk["new_lines"] and start > 0 and not result[start - 1].endswith("\n"):
            result[start - 1] += "\n"
        result[start:end] = hunk["new_lines"]

    return "".join(result)


def _parse_hunks(diff_text: str, original_lines: list[str]) -> list[dict]:
    hunks = []
    hunk_header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    lines = diff_text.splitlines(keepends=True)

    i = 0
    while i < len(lines):
        m = hunk_header.match(lines[i])
        if not m:
            i += 1
            continue
        orig_start = int(m.group(1))
        orig_len = int(m.group(2) or 1)
        i += 1
        new_lines = []
        consumed = 0
        pos = orig_start - 1  # 0-indexed cursor into original_lines

        # Consume EXACTLY orig_len context/removed lines -- a real unified
        # diff hunk never contains more than that. The old version kept
        # consuming lines past this boundary (a stub cap of "orig_len + 50"
        # that never actually enforced anything), which let a model that
        # forgot to omit a trailing context line silently sweep an
        # untouched line of the file into the hunk and mangle it.
        while i < len(lines) and consumed < orig_len:
            line = lines[i]
            if line.startswith("+") and not line.startswith("+++"):
                new_lines.append(line[1:])
                i += 1
                continue
            elif line.startswith(" "):
                content = line[1:]
                marker = " "
            elif line.startswith("-") and not line.startswith("---"):
                content = line[1:]
                marker = "-"
            else:
                break

            # Context and removed lines must actually match what's in the
            # original file at this position. A model that gets a hunk
            # header's line numbers wrong, or garbles which lines are
            # context vs. changed, previously got spliced in anyway with
            # no check at all -- silently producing wrong code instead of
            # a clear, early failure.
            if pos >= len(original_lines) or not _eq_ignoring_final_newline(original_lines[pos], content):
                actual = original_lines[pos] if pos < len(original_lines) else "<end of file>"
                raise ValueError(
                    f"hunk {marker!r} line at original line {pos + 1} doesn't match "
                    f"the file: diff says {content!r}, file has {actual!r}"
                )
            if marker == " ":
                # Keep the buffer's own bytes for unchanged lines, so a file
                # with no trailing newline stays that way unless the fix
                # actually touches its last line.
                new_lines.append(original_lines[pos])
            pos += 1
            consumed += 1
            i += 1

        # Trailing '+' lines with no more context/removed lines to consume
        # still belong to this hunk (pure insertions at the end).
        while i < len(lines) and lines[i].startswith("+") and not lines[i].startswith("+++"):
            new_lines.append(lines[i][1:])
            i += 1

        if consumed != orig_len:
            raise ValueError(
                f"hunk header claims {orig_len} original line(s) but only "
                f"{consumed} could be matched against the file"
            )

        # A context line taken from a buffer with no trailing newline can be
        # followed by added lines inside the same hunk; terminate it first.
        for k in range(len(new_lines) - 1):
            if not new_lines[k].endswith("\n"):
                new_lines[k] += "\n"

        hunks.append({"orig_start": orig_start, "orig_len": orig_len, "new_lines": new_lines})
    return hunks

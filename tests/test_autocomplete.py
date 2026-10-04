"""Pure-logic tests for the autocomplete engine (no display needed)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from client.autocomplete import analyze_context, parse_snippet, query, rank, line_state, in_literal
from client.completion_data import completions_for, member_completions, MODULES


def labels(res):
    return [c.label for c in res[1]] if res else []


def test_parse_snippet_stops_and_indent():
    text, stops = parse_snippet("for (int ${1:i} = 0; ${1:i} < ${2:n}; ${1:i}++) {\n\t$0\n}", "    ", "  ")
    assert text == "for (int i = 0; i < n; i++) {\n      \n  }"
    nums = [s[0] for s in stops]
    assert nums == [1, 1, 2, 1, 0]
    n1 = [s for s in stops if s[0] == 1][0]
    assert text[n1[1]:n1[2]] == "i"


def test_parse_snippet_plain_text_has_no_stops():
    assert parse_snippet("while", "    ", "") == ("while", [])


def test_literal_detection():
    assert line_state('x = "abc', "python") == ("str", '"')
    assert line_state("x = 1  # it's", "python")[0] == "comment"
    assert line_state("int a; // don't", "c")[0] == "comment"
    assert line_state('printf("a\\"b', "c") == ("str", '"')
    assert in_literal("   * foo", "/* start\n   * foo", "c")
    assert not in_literal("x", "/* a */\nx", "c")
    assert in_literal("hello", 'a = """doc\nhello', "python")


def test_include_context_c():
    ctx = analyze_context("#include <std", "#include <std", "c")
    assert (ctx.kind, ctx.prefix, ctx.extra) == ("include", "std", "<")
    ctx = analyze_context("#include ", "#include ", "c")
    assert ctx.kind == "include" and ctx.extra == ""
    res = query("c", "#include <std", "#include <std", "#include <std")
    assert labels(res)[:3] == ["stdio.h", "stdlib.h", "stddef.h"] or "stdio.h" in labels(res)


def test_hash_prefix_offers_full_include_lines():
    res = query("c", "#inc", "#inc", "#inc")
    assert "#include <stdio.h>" in labels(res)
    assert "#include <stdlib.h>" in labels(res)


def test_no_popup_in_comments_or_strings():
    assert query("python", "# hello wor", "# hello wor", "# hello wor") is None
    assert query("c", 'puts("hel', 'puts("hel', 'puts("hel') is None
    assert query("java", "// retu", "// retu", "// retu") is None


def test_min_chars_for_auto_but_not_manual():
    assert query("python", "d", "d", "d") is None
    assert query("python", "d", "d", "d", manual=True) is not None


def test_snippets_beat_plain_keywords():
    res = query("python", "fo", "fo", "fo")
    assert labels(res)[0] == "for"
    assert res[1][0].kind == "snippet"


def test_exact_plain_word_is_not_offered_alone():
    # `zzz_var` is only in the file once (the word being typed) -> nothing to offer
    assert query("c", "zzz_var", "zzz_var", "zzz_var") is None
    # `int` also prefixes int8_t & co, so the list stays, but loose matches
    # (fprintf contains i-n-t) must not creep in
    res = labels(query("c", "int", "int", "int"))
    assert res[0] == "int" and "fprintf" not in res
    # a snippet with the same name as the typed word is still offered
    assert "for" in labels(query("c", "for", "for", "for"))


def test_document_words_are_offered():
    src = "total_count = 0\ntotal_count += 1\ntot"
    res = query("python", "tot", src, src)
    assert "total_count" in labels(res)


def test_member_completion():
    res = query("java", "Math.sq", "Math.sq", "Math.sq")
    assert labels(res)[0] == "sqrt"
    res = query("java", "System.out.pr", "System.out.pr", "")
    assert set(labels(res)) >= {"println", "print", "printf"}
    res = query("python", "os.path.jo", "os.path.jo", "")
    assert labels(res) == ["join"]
    # unknown receiver falls back to the generic method list
    res = query("python", "items.app", "items.app", "")
    assert "append" in labels(res)
    # number literals and ellipsis are not member access
    assert analyze_context("x = 3.", "x = 3.", "python") is None
    assert analyze_context("x[..", "x[..", "python") is None


def test_c_has_no_member_popup():
    assert analyze_context("p.nam", "p.nam", "c") is None
    assert analyze_context("p->nam", "p->nam", "c") is None


def test_import_context():
    res = query("python", "import ma", "import ma", "")
    assert "math" in labels(res)
    res = query("java", "import java.util.Sca", "import java.util.Sca", "")
    assert "java.util.Scanner" in labels(res)
    res = query("java", "import Scan", "import Scan", "")
    assert "java.util.Scanner" in labels(res)      # matches on the last segment
    # `from x import <names>` has no static data -> no module popup
    assert analyze_context("from os import pa", "from os import pa", "python").kind != "import"


def test_ranking_prefers_same_case_then_short():
    cands = completions_for("python")
    out = [c.label for c in rank(cands, "pr")]
    assert out[0] == "print"
    assert "printf" in out


def test_data_integrity():
    for lang in ("python", "c", "java"):
        items = completions_for(lang)
        assert len({c.label for c in items}) == len(items)         # deduped
        for c in items:
            assert c.label and c.kind and c.body
        assert MODULES[lang]
    assert member_completions("python", "math")

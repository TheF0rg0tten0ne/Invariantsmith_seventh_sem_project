#!/usr/bin/env python3
"""
Mines GitHub for (broken_code, error, fixed_code) training triples.

Strategy: search commits whose message matches a "fix" pattern
(e.g. "fix flake8", "fix lint", "fix NameError", "resolve unused import")
in Python repos, then diff parent -> commit to get the before/after.

This gives natural, real-world (bug, fix) pairs at scale without hand
labeling. Output format matches what fixer.py expects the model to learn:
a JSON object per example with error context + a unified diff + a short
rationale (derived from the commit message).

Usage:
    export GITHUB_TOKEN=ghp_xxx        # recommended, raises rate limits a lot
    python mine_fix_pairs.py --language python --query "fix flake8 error" \
        --max-results 200 --out training_data.jsonl
    python mine_fix_pairs.py --language c --all-patterns --out training_data.jsonl
    python mine_fix_pairs.py --language java --all-patterns --out training_data.jsonl

Requires only `requests` (already in requirements.txt) and network access
to api.github.com / github.com.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

GITHUB_API = "https://api.github.com"

# Each language gets its own commit-search vocabulary (matching that
# ecosystem's actual lint/static-analysis tools) and its own file
# extensions to keep in a commit's diff. Mining "fix lint" against
# GitHub's Python corpus and calling it done for C/Java would just
# re-mine more Python -- these need to be genuinely different queries,
# not a shared list run three times with a different `language:` filter.
FIX_COMMIT_PATTERNS = {
    "python": [
        "fix flake8",
        "fix lint",
        "fix pyflakes",
        "fix unused import",
        "fix undefined name",
        "resolve NameError",
        "fix syntax error",
    ],
    "c": [
        "fix cppcheck",
        "fix clang-tidy",
        "fix -Wunused-variable",
        "fix segfault",
        "fix memory leak",
        "fix null pointer dereference",
        "fix uninitialized variable",
        "fix compiler warning",
    ],
    "java": [
        "fix checkstyle",
        "fix spotbugs",
        "fix findbugs",
        "fix unused import",
        "fix NullPointerException",
        "resolve compiler warning",
        "fix unchecked cast",
    ],
}

_LANG_EXTENSIONS = {
    "python": (".py",),
    "c": (".c", ".h"),
    "java": (".java",),
}

_GITHUB_LANGUAGE_QUALIFIER = {
    "python": "Python",
    "c": "C",
    "java": "Java",
}


def _headers():
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def search_commits(query: str, language: str, max_results: int = 100) -> list[dict]:
    """Search commits via GitHub's commit search API, scoped to one language."""
    gh_lang = _GITHUB_LANGUAGE_QUALIFIER[language]
    results = []
    page = 1
    per_page = min(100, max_results)
    while len(results) < max_results:
        resp = requests.get(
            f"{GITHUB_API}/search/commits",
            params={"q": f"{query} language:{gh_lang}", "per_page": per_page, "page": page},
            headers={**_headers(), "Accept": "application/vnd.github.cloak-preview+json"},
            timeout=30,
        )
        if resp.status_code == 403:
            print("Rate limited. Set GITHUB_TOKEN or wait. Stopping early.", file=sys.stderr)
            break
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            break
        results.extend(items)
        page += 1
        time.sleep(1)  # be polite to the API
    return results[:max_results]


def get_commit_diff(repo_full_name: str, sha: str) -> dict | None:
    resp = requests.get(
        f"{GITHUB_API}/repos/{repo_full_name}/commits/{sha}",
        headers=_headers(), timeout=30,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def extract_language_file_pairs(commit_data: dict, language: str) -> list[dict]:
    """Pull (patch, filename) for each modified file matching this
    language's extensions in a commit."""
    exts = _LANG_EXTENSIONS[language]
    pairs = []
    for f in commit_data.get("files", []):
        if not f.get("filename", "").endswith(exts):
            continue
        if "patch" not in f:
            continue  # binary or too-large diffs have no patch
        pairs.append({
            "filename": f["filename"],
            "patch": f["patch"],
            "status": f["status"],
        })
    return pairs


def build_training_examples(query: str, language: str, max_results: int, out_path: Path) -> int:
    commits = search_commits(query, language, max_results)
    count = 0
    with open(out_path, "a", encoding="utf-8") as out:
        for item in commits:
            repo = item["repository"]["full_name"]
            sha = item["sha"]
            message = item["commit"]["message"].splitlines()[0]

            commit_data = get_commit_diff(repo, sha)
            if not commit_data:
                continue

            for pair in extract_language_file_pairs(commit_data, language):
                example = {
                    "language": language,
                    "repo": repo,
                    "sha": sha,
                    "filename": pair["filename"],
                    "commit_message": message,
                    "diff": pair["patch"],
                    "rationale": message,  # naive rationale; refine with a labeling pass
                }
                out.write(json.dumps(example) + "\n")
                count += 1
            time.sleep(0.5)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=sorted(FIX_COMMIT_PATTERNS), default="python",
                         help="Which language's commit corpus and query vocabulary to mine")
    parser.add_argument("--query", default=None,
                         help="Commit search query, e.g. 'fix flake8 error'. "
                              "Defaults to this language's first built-in pattern.")
    parser.add_argument("--max-results", type=int, default=100)
    parser.add_argument("--out", type=Path, default=Path("training_data.jsonl"))
    parser.add_argument("--all-patterns", action="store_true",
                         help="Run through all built-in fix-commit patterns for --language")
    args = parser.parse_args()

    patterns = FIX_COMMIT_PATTERNS[args.language]
    queries = patterns if args.all_patterns else [args.query or patterns[0]]
    total = 0
    for q in queries:
        print(f"Searching ({args.language}): {q!r}")
        n = build_training_examples(q, args.language, args.max_results, args.out)
        print(f"  -> {n} examples")
        total += n

    print(f"Done. {total} total examples written to {args.out}")


if __name__ == "__main__":
    main()

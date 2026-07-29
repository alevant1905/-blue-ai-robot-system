"""Produce a shareable snapshot of this repo with private details replaced.

This repository is the working history of a system that runs in a real home, so
the code names real people, inboxes and machines. Publishing it means shipping
none of that. Rather than editing the live tree — which would risk breaking a
running robot — this script writes a *separate* sanitized copy that can be
pushed to a public repository as a single clean commit.

The substitution table lives OUTSIDE this file, in `data/sanitize_map.json`
(untracked), so the script itself contains no private information and is safe to
publish alongside the code.

    python scripts/publish_sanitized.py ../blue-public

What it does:
  1. exports the tracked files at HEAD (never untracked junk or ignored data),
  2. applies the substitutions from the map,
  3. refuses to finish if any forbidden token survives anywhere in the output,
  4. byte-compiles every Python file so an unusable snapshot cannot ship.

Verification is the point: step 3 is what makes the result trustworthy, so a
failure there is a hard error rather than a warning.
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".css", ".js", ".json", ".ps1", ".html", ".cfg",
    ".ini", ".toml", ".yml", ".yaml", "",
}
MAP_PATH = Path("data/sanitize_map.json")

README_NOTE = """

## Configuring this for your own household

The household names, email addresses, network hostnames and course codes in this
repository are **placeholders**, not real values. Before running it, change:

- `_USER_PROFILES`, `_DEVICE_OWNER` and `_CHAT_ONLY_USERS` in `bluetools.py` —
  who lives here and which device belongs to whom.
- `config.py` — the household roster.
- The Gmail addresses in `bluetools.py` (`GMAIL_USER_EMAIL`, `BLUE_OWN_EMAIL`,
  `BLUE_BCC_EMAIL`); all three also read from environment variables.
- The Tailscale hostname and IP in `blue/server/pages/chat.py` and
  `bluetools.py`, if you use Tailscale to reach the server from a phone.

Secrets are never stored in code: Gmail uses `credentials.json` / `token.pickle`
(both gitignored) and the smart-home and music integrations read environment
variables.
"""


def _load_map(root: Path) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], List[str]]:
    """Return (literal rules, word rules, forbidden tokens) from the map file."""
    path = root / MAP_PATH
    if not path.exists():
        sys.exit(
            f"missing {MAP_PATH}. Create it (it is gitignored) as:\n"
            '{\n  "literals": {"real@email": "placeholder@example.com"},\n'
            '  "words": {"RealName": "Placeholder"},\n'
            '  "forbidden": ["extra token to assert is absent"]\n}'
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    literals = sorted(
        data.get("literals", {}).items(), key=lambda kv: len(kv[0]), reverse=True
    )
    words = sorted(
        data.get("words", {}).items(), key=lambda kv: len(kv[0]), reverse=True
    )
    forbidden = list(data.get("forbidden", []))
    forbidden += [key for key, _ in literals] + [key for key, _ in words]
    return literals, words, forbidden


def _cased(found: str, replacement: str) -> str:
    """Mirror the casing of what was matched, so identifiers stay identifiers."""
    # A multi-word or deliberately capitalised replacement is authored the way it
    # should read ("KCI" -> "Northside High"), so mirroring an all-caps match
    # would shout it.
    if " " in replacement or any(char.isupper() for char in replacement[1:]):
        return replacement
    if found.isupper() and len(found) > 1:
        return replacement.upper()
    if found.islower():
        return replacement.lower()
    if found[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _substitute(text: str, literals, words) -> str:
    for target, replacement in literals:
        # An email written into a regex has its dots escaped, so the literal
        # form alone would miss it — and the replacement has to go back in
        # escaped too, or the pattern silently loosens to match any character.
        variants = [(target, replacement)]
        if "." in target:
            variants.append(
                (target.replace(".", r"\."), replacement.replace(".", r"\."))
            )
        for found, substitute in variants:
            pattern = re.compile(re.escape(found), re.IGNORECASE)
            text = pattern.sub(
                lambda m, r=substitute: _cased(m.group(0), r), text
            )
    for target, replacement in words:
        # Deliberately NOT \b: facts are keyed off names ("athena_age": "10"),
        # and \b does not fire before an underscore, so the value would be
        # renamed while the key was orphaned. Treating "_" as a boundary renames
        # both, while still refusing to touch a name glued to letters or digits
        # ("Christmas" keeps its Chris, "ignoring" keeps its Nori).
        pattern = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(target)}(?![A-Za-z0-9])", re.IGNORECASE
        )
        text = pattern.sub(lambda m, r=replacement: _cased(m.group(0), r), text)
    return text


def _export_head(root: Path, destination: Path) -> None:
    """Copy the tracked files at HEAD — never untracked or ignored paths."""
    archive = Path(tempfile.mkdtemp()) / "head.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=root, check=True,
    )
    shutil.unpack_archive(str(archive), str(destination), format="tar")
    shutil.rmtree(archive.parent, ignore_errors=True)


def _scan_forbidden(destination: Path, forbidden: List[str]) -> List[str]:
    # Same boundary rule as the substitution, or a survivor like "athena_age"
    # would pass a \b-based scan and ship.
    patterns = [
        (
            token,
            re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
                re.IGNORECASE,
            ),
        )
        for token in forbidden if token
    ]
    # Build artifacts embed the absolute source path (which contains the OS
    # username) and are never committed, so scanning them only raises false
    # alarms — but they must be skipped explicitly, or a scan run after a test
    # run looks like a leak.
    skip_dirs = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
    hits = []
    for path in sorted(destination.rglob("*")):
        if not path.is_file() or skip_dirs & set(path.parts):
            continue
        if path.suffix.lower() in {".pyc", ".pyo", ".png", ".jpg", ".pdf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for token, pattern in patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append(f"{path.relative_to(destination)}:{line}: {token}")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="directory to write the snapshot to")
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite the destination if it already exists",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    destination = Path(args.destination).resolve()
    if destination.exists():
        if not args.force:
            return print(f"{destination} exists; pass --force to replace it") or 1
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    literals, words, forbidden = _load_map(root)
    _export_head(root, destination)

    changed = 0
    for path in sorted(destination.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        original = path.read_text(encoding="utf-8", errors="surrogateescape")
        cleaned = _substitute(original, literals, words)
        if cleaned != original:
            path.write_text(cleaned, encoding="utf-8", errors="surrogateescape")
            changed += 1
    print(f"rewrote {changed} files")

    readme = destination / "README.md"
    if readme.exists() and "Configuring this for your own household" not in \
            readme.read_text(encoding="utf-8", errors="ignore"):
        with readme.open("a", encoding="utf-8") as handle:
            handle.write(README_NOTE)

    # The snapshot is only publishable if nothing private survived.
    hits = _scan_forbidden(destination, forbidden)
    if hits:
        print(f"\nREFUSING TO PUBLISH — {len(hits)} private token(s) remain:")
        for hit in hits[:40]:
            print("  " + hit)
        return 1
    print("clean: no forbidden token found in the snapshot")

    broken = []
    # Not os.devnull: on Windows py_compile refuses to write a .pyc to `nul`.
    scratch = Path(tempfile.mkdtemp())
    for path in sorted(destination.rglob("*.py")):
        try:
            py_compile.compile(
                str(path), doraise=True, cfile=str(scratch / "check.pyc")
            )
        except py_compile.PyCompileError as exc:
            broken.append(f"{path.relative_to(destination)}: {str(exc)[:120]}")
    shutil.rmtree(scratch, ignore_errors=True)
    if broken:
        print(f"\nREFUSING TO PUBLISH — {len(broken)} file(s) will not compile:")
        for item in broken:
            print("  " + item)
        return 1
    print("all python files compile")
    print(f"\nsnapshot ready: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

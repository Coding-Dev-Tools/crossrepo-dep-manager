"""Apply dependency fixes across repos."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path


def _read_pyproject(path: Path) -> str:
    """Read pyproject.toml as text."""
    return path.read_text(encoding="utf-8")


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text to *path* atomically via tempfile + fsync + os.replace.

    If the process crashes mid-write, the original file is preserved intact
    because the new content is written to a sibling temp file first and only
    swapped in via ``os.replace`` (atomic on POSIX, best-effort on Windows).
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up the temp file on any failure (including KeyboardInterrupt)
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def replace_dep_in_text(text: str, dep_name: str, new_raw: str) -> tuple[str, int]:
    """Replace a dependency string in pyproject.toml text.

    Matches dep name + optional extras + version spec (e.g. click>=8.0 or mcp[server]>=1.0)
    and replaces just the dep+version portion, preserving surrounding quotes/commas.
    Returns (new_text, replacement_count).

    Comment lines (first non-whitespace character is ``#``) are never touched,
    so a dependency name appearing in a ``# deprecated`` note is not corrupted.
    """
    escaped_name = re.escape(dep_name)
    pattern = (
        rf"({escaped_name}(?:\[[^\]]*\])?"  # dep name + optional extras
        rf"\s*[<>=!~.]+"  # comparison operator(s) — a REAL operator char is required
        rf"[\d.,<>=!~\w]*"  # version numbers and compound specs
        rf'(?:\s*;[^"\n]*)?)'  # optional PEP 508 environment marker
    )
    # Bare declaration: dep name (+extras) with NO version specifier at all,
    # e.g. "click" or "mcp[server]". Only matched when followed by a token
    # boundary (quote / comma / closing bracket / whitespace+quote / EOL) so a
    # name mentioned inside prose ("uses click for CLI") or a longer package
    # name ("clickhouse") is never corrupted.
    bare_pattern = (
        rf"({escaped_name}(?:\[[^\]]*\])?)"  # dep name + optional extras only
        rf"(?=\s*[\"',\]]|\s*$)"  # must end the dependency token
    )

    result_lines = []
    count = 0
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            result_lines.append(line)
            continue
        new_line, n = re.subn(pattern, new_raw, line)
        if n == 0:
            new_line, n = re.subn(bare_pattern, new_raw, line)
        result_lines.append(new_line)
        count += n
    return "\n".join(result_lines), count


def apply_fix(
    repos_dir: str | Path,
    repo: str,
    dep_name: str,
    new_raw: str,
    dry_run: bool = True,
) -> bool:
    """Apply a single dependency fix to a repo's pyproject.toml.

    Returns True if a change was made.
    """
    pyproject = Path(repos_dir) / repo / "pyproject.toml"
    if not pyproject.exists():
        return False

    original = _read_pyproject(pyproject)
    updated, count = replace_dep_in_text(original, dep_name, new_raw)

    if count == 0 or updated == original:
        return False

    if not dry_run:
        _atomic_write_text(pyproject, updated)
    return True


def apply_all_fixes(
    repos_dir: str | Path,
    fixes: dict[str, dict[str, str]],
    dry_run: bool = True,
) -> list[dict]:
    """Apply all fixes and return a list of results.

    Args:
        fixes: {repo: {dep_name: new_raw}}
        dry_run: If True, don't write changes

    Returns: [{repo, dep, new, changed, dry_run}, ...]
    """
    results = []
    for repo, dep_fixes in sorted(fixes.items()):
        for dep_name, new_raw in sorted(dep_fixes.items()):
            changed = apply_fix(repos_dir, repo, dep_name, new_raw, dry_run=dry_run)
            results.append(
                {
                    "repo": repo,
                    "dep": dep_name,
                    "new": new_raw,
                    "changed": changed,
                    "dry_run": dry_run,
                }
            )
    return results

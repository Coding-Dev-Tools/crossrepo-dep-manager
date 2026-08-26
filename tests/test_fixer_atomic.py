"""Test atomic write safety in fixer.apply_fix."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from crossrepo_dep_manager.fixer import apply_fix


def test_apply_fix_uses_atomic_write(tmp_path: Path) -> None:
    """apply_fix must write via tempfile+os.replace, not direct overwrite.

    A direct write_text() truncates the file immediately, then writes.
    If the process crashes between truncate and write-complete, the
    pyproject.toml is corrupted (zero bytes or partial content).

    Atomic pattern: write to a .tmp sibling, fsync, then os.replace()
    which is atomic on POSIX and as close to atomic as Windows allows.
    """
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    pyproject = repo_dir / "pyproject.toml"
    original_content = '[project]\ndependencies = ["click>=7.0"]\n'
    pyproject.write_text(original_content, encoding="utf-8")

    # Simulate a crash at the os.replace() swap point.
    # With atomic write, the original must survive because the new
    # content is still in the temp file and never swapped in.
    real_replace = os.replace
    crash_triggered = False

    def crashing_replace(src, dst):
        nonlocal crash_triggered
        if str(dst).endswith("pyproject.toml"):
            crash_triggered = True
            raise OSError("Simulated disk full during replace")
        return real_replace(src, dst)

    with patch.object(os, "replace", crashing_replace), pytest.raises(OSError, match="Simulated disk full"):
        apply_fix(
            repos_dir=tmp_path,
            repo="myrepo",
            dep_name="click",
            new_raw="click>=8.0",
            dry_run=False,
        )

    assert crash_triggered, "The crash mock must have fired on os.replace"

    # CRITICAL: original content must survive the crash
    survived = pyproject.read_text(encoding="utf-8")
    assert survived == original_content, (
        f"Original pyproject.toml corrupted by crash! Got: {survived!r}"
    )

    # The temp file should be cleaned up
    tmp_files = list(repo_dir.glob("*.tmp"))
    assert not tmp_files, f"Temp files must be cleaned up after crash: {tmp_files}"


def test_apply_fix_no_tmp_leftover_on_success(tmp_path: Path) -> None:
    """Successful apply_fix must not leave .tmp artifacts behind."""
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    pyproject = repo_dir / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["click>=7.0"]\n', encoding="utf-8"
    )

    changed = apply_fix(
        repos_dir=tmp_path,
        repo="myrepo",
        dep_name="click",
        new_raw="click>=8.0",
        dry_run=False,
    )
    assert changed is True

    # Verify the fix was applied
    content = pyproject.read_text(encoding="utf-8")
    assert "click>=8.0" in content

    # No temp file should remain
    tmp_files = list(repo_dir.glob("*.tmp"))
    assert not tmp_files, f"Temp files left behind: {tmp_files}"

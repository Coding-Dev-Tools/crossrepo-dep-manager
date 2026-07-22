"""Tests for cross-repo dependency fixer."""
from __future__ import annotations

from pathlib import Path

from crossrepo_dep_manager.fixer import _read_pyproject, apply_all_fixes, apply_fix


def _make_pyproject(repo_dir: Path, deps: list[str] | None = None) -> Path:
    """Create a minimal pyproject.toml in repo_dir."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    pyproject = repo_dir / "pyproject.toml"
    lines = [
        "[build-system]",
        'requires = ["hatchling"]',
        'build-backend = "hatchling.build"',
        "",
        "[project]",
        f'name = "{repo_dir.name}"',
        'version = "0.1.0"',
    ]
    if deps:
        lines.append("dependencies = [")
        for d in deps:
            lines.append(f'    "{d}",')
        lines.append("]")
    pyproject.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return pyproject


def test_apply_fix_dry_run(tmp_path):
    """Dry run returns True but does NOT modify the file."""
    repo = tmp_path / "test-repo"
    _make_pyproject(repo, ["click>=8.0"])
    original = _read_pyproject(repo / "pyproject.toml")

    result = apply_fix(str(tmp_path), "test-repo", "click", "click>=8.1.0", dry_run=True)
    assert result is True, "dry_run should return True when change would be made"

    after = _read_pyproject(repo / "pyproject.toml")
    assert after == original, "dry_run must NOT modify the file"


def test_apply_fix_apply_writes(tmp_path):
    """apply=True actually modifies the file."""
    repo = tmp_path / "test-repo"
    _make_pyproject(repo, ["click>=8.0"])

    result = apply_fix(str(tmp_path), "test-repo", "click", "click>=8.1.0", dry_run=False)
    assert result is True

    content = _read_pyproject(repo / "pyproject.toml")
    assert "click>=8.1.0" in content
    assert "click>=8.0" not in content


def test_apply_fix_no_change(tmp_path):
    """Returns False when file already has the desired value."""
    repo = tmp_path / "test-repo"
    _make_pyproject(repo, ["click>=8.1.0"])

    result = apply_fix(str(tmp_path), "test-repo", "click", "click>=8.1.0", dry_run=True)
    assert result is False, "no change should return False"


def test_apply_fix_missing_pyproject(tmp_path):
    """Returns False when pyproject.toml doesn't exist."""
    result = apply_fix(str(tmp_path), "nonexistent-repo", "click", "click>=8.1.0", dry_run=True)
    assert result is False, "missing file should return False"


def test_apply_fix_multiple_deps(tmp_path):
    """Only the targeted dependency is replaced, others are untouched."""
    repo = tmp_path / "multi-repo"
    _make_pyproject(repo, ["click>=8.0", "rich>=13.0.0", "packaging>=23.0"])

    apply_fix(str(tmp_path), "multi-repo", "rich", "rich>=14.0.0", dry_run=False)
    content = _read_pyproject(repo / "pyproject.toml")
    assert "rich>=14.0.0" in content
    assert "click>=8.0" in content
    assert "packaging>=23.0" in content
    assert "rich>=13.0" not in content


def test_apply_fix_preserves_comment_lines(tmp_path):
    """Comment lines containing the dep name must not be replaced."""
    repo = tmp_path / "comment-repo"
    repo.mkdir(parents=True)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        '# old click>=8.0 deprecated\n'
        'dependencies = [\n'
        '    "click>=8.0",\n'
        ']\n',
        encoding="utf-8",
    )
    apply_fix(str(tmp_path), "comment-repo", "click", "click>=8.1.0", dry_run=False)
    content = _read_pyproject(pyproject)
    assert content.count("click>=8.1.0") == 1
    assert "old click>=8.1.0" not in content


# ---- apply_all_fixes tests ----

def test_apply_all_fixes_empty(tmp_path):
    """Empty fixes dict returns empty list."""
    results = apply_all_fixes(str(tmp_path), {}, dry_run=True)
    assert results == []


def test_apply_all_fixes_single_repo(tmp_path):
    """Single fix across one repo works."""
    repo = tmp_path / "single-repo"
    _make_pyproject(repo, ["click>=8.0"])

    fixes = {"single-repo": {"click": "click>=8.1.0"}}
    results = apply_all_fixes(str(tmp_path), fixes, dry_run=True)
    assert len(results) == 1
    assert results[0] == {
        "repo": "single-repo",
        "dep": "click",
        "new": "click>=8.1.0",
        "changed": True,
        "dry_run": True,
    }

    # Verify file NOT written (dry run)
    content = _read_pyproject(repo / "pyproject.toml")
    assert "click>=8.0" in content


def test_apply_all_fixes_multiple_repos(tmp_path):
    """Fixes across multiple repos."""
    _make_pyproject(tmp_path / "repo-a", ["click>=8.0"])
    _make_pyproject(tmp_path / "repo-b", ["click>=8.0"])
    _make_pyproject(tmp_path / "repo-c", ["rich>=13.0.0"])

    fixes = {
        "repo-a": {"click": "click>=8.1.0"},
        "repo-b": {"click": "click>=8.1.0"},
        "repo-c": {"rich": "rich>=14.0.0"},
    }
    results = apply_all_fixes(str(tmp_path), fixes, dry_run=False)
    assert len(results) == 3
    changed = [r for r in results if r["changed"]]
    assert len(changed) == 3

    # Verify all files modified
    assert "click>=8.1.0" in _read_pyproject(tmp_path / "repo-a" / "pyproject.toml")
    assert "click>=8.1.0" in _read_pyproject(tmp_path / "repo-b" / "pyproject.toml")
    assert "rich>=14.0.0" in _read_pyproject(tmp_path / "repo-c" / "pyproject.toml")


def test_apply_all_fixes_some_noop(tmp_path):
    """Only repos needing changes are reported as changed."""
    _make_pyproject(tmp_path / "repo-a", ["click>=8.1.0"])  # already correct
    _make_pyproject(tmp_path / "repo-b", ["click>=8.0"])    # needs update

    fixes = {
        "repo-a": {"click": "click>=8.1.0"},
        "repo-b": {"click": "click>=8.1.0"},
    }
    results = apply_all_fixes(str(tmp_path), fixes, dry_run=False)
    assert len(results) == 2
    for r in results:
        if r["repo"] == "repo-a":
            assert r["changed"] is False
        if r["repo"] == "repo-b":
            assert r["changed"] is True


def test_apply_all_fixes_missing_repo(tmp_path):
    """Missing repo silently returns changed=False."""
    fixes = {"nonexistent": {"click": "click>=8.1.0"}}
    results = apply_all_fixes(str(tmp_path), fixes, dry_run=True)
    assert len(results) == 1
    assert results[0]["changed"] is False


def test_apply_all_fixes_dry_run_flag(tmp_path):
    """dry_run=False actually writes; dry_run=True doesn't."""
    _make_pyproject(tmp_path / "target", ["click>=8.0"])

    # dry run
    results_dry = apply_all_fixes(str(tmp_path), {"target": {"click": "click>=8.1.0"}}, dry_run=True)
    assert results_dry[0]["dry_run"] is True
    assert "click>=8.0" in _read_pyproject(tmp_path / "target" / "pyproject.toml")

    # apply
    results_apply = apply_all_fixes(str(tmp_path), {"target": {"click": "click>=8.1.0"}}, dry_run=False)
    assert results_apply[0]["dry_run"] is False
    assert "click>=8.1.0" in _read_pyproject(tmp_path / "target" / "pyproject.toml")


def test_apply_all_fixes_multiple_deps_per_repo(tmp_path):
    """A repo can have multiple deps fixed in one call."""
    _make_pyproject(tmp_path / "multi", ["click>=8.0", "rich>=13.0.0"])

    fixes = {
        "multi": {
            "click": "click>=8.1.0",
            "rich": "rich>=14.0.0",
        }
    }
    results = apply_all_fixes(str(tmp_path), fixes, dry_run=False)
    assert len(results) == 2
    assert all(r["changed"] for r in results)
    content = _read_pyproject(tmp_path / "multi" / "pyproject.toml")
    assert "click>=8.1.0" in content
    assert "rich>=14.0.0" in content

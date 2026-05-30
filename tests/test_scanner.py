"""Tests for cross-repo dependency scanner."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from crossrepo_dep_manager.scanner import (
    scan_repo,
    scan_all,
    build_dep_index,
    find_conflicts,
    recommend_version,
    generate_fix,
    DepEntry,
)


def _make_repo(tmp: Path, name: str, deps: list[str], opt_deps: dict[str, list[str]] | None = None) -> Path:
    """Create a minimal repo with pyproject.toml."""
    repo = tmp / name
    repo.mkdir(parents=True, exist_ok=True)
    lines = [
        "[build-system]",
        'requires = ["hatchling"]',
        'build-backend = "hatchling.build"',
        "",
        "[project]",
        f'name = "{name}"',
        'version = "0.1.0"',
    ]
    if deps:
        lines.append("dependencies = [")
        for d in deps:
            lines.append(f'    "{d}",')
        lines.append("]")
    if opt_deps:
        lines.append("")
        lines.append("[project.optional-dependencies]")
        for key, vals in opt_deps.items():
            lines.append(f'{key} = [')
            for v in vals:
                lines.append(f'    "{v}",')
            lines.append("]")
    (repo / "pyproject.toml").write_text("\n".join(lines) + "\n")
    (repo / "src").mkdir(exist_ok=True)
    return repo


class TestScanRepo:
    def test_basic_deps(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo", ["click>=8.1.0", "rich>=13.0.0"])
        entries = scan_repo(repo)
        assert len(entries) == 2
        assert entries[0].name == "click"
        assert entries[0].specifiers == ">=8.1.0"
        assert entries[0].repo == "myrepo"
        assert entries[1].name == "rich"

    def test_no_pyproject(self, tmp_path):
        entries = scan_repo(tmp_path / "nonexistent")
        assert entries == []

    def test_optional_deps(self, tmp_path):
        repo = _make_repo(
            tmp_path, "myrepo",
            ["click>=8.1.0"],
            {"dev": ["pytest>=7.0.0", "ruff>=0.4.0"]},
        )
        entries = scan_repo(repo)
        names = [e.name for e in entries]
        assert "click" in names
        assert "pytest" in names
        assert "ruff" in names

    def test_empty_deps(self, tmp_path):
        repo = _make_repo(tmp_path, "empty", [])
        entries = scan_repo(repo)
        assert entries == []


class TestScanAll:
    def test_multiple_repos(self, tmp_path):
        _make_repo(tmp_path, "repo-a", ["click>=8.1.0"])
        _make_repo(tmp_path, "repo-b", ["click>=8.0", "rich>=13.0.0"])
        results = scan_all(tmp_path)
        assert "repo-a" in results
        assert "repo-b" in results

    def test_skips_non_pyproject(self, tmp_path):
        _make_repo(tmp_path, "has-pyproject", ["click>=8.1.0"])
        no_pyproject = tmp_path / "no-pyproject"
        no_pyproject.mkdir()
        results = scan_all(tmp_path)
        assert "has-pyproject" in results
        assert "no-pyproject" not in results


class TestBuildDepIndex:
    def test_index(self, tmp_path):
        _make_repo(tmp_path, "repo-a", ["click>=8.1.0"])
        _make_repo(tmp_path, "repo-b", ["click>=8.0"])
        all_entries = scan_all(tmp_path)
        index = build_dep_index(all_entries)
        assert "click" in index
        assert len(index["click"]) == 2


class TestFindConflicts:
    def test_conflict_detected(self, tmp_path):
        _make_repo(tmp_path, "repo-a", ["click>=8.1.0"])
        _make_repo(tmp_path, "repo-b", ["click>=8.0"])
        all_entries = scan_all(tmp_path)
        index = build_dep_index(all_entries)
        conflicts = find_conflicts(index, min_repos=2)
        assert len(conflicts) == 1
        assert conflicts[0].is_conflict
        assert conflicts[0].package == "click"

    def test_no_conflict(self, tmp_path):
        _make_repo(tmp_path, "repo-a", ["click>=8.1.0"])
        _make_repo(tmp_path, "repo-b", ["click>=8.1.0"])
        all_entries = scan_all(tmp_path)
        index = build_dep_index(all_entries)
        conflicts = find_conflicts(index, min_repos=2)
        assert len(conflicts) == 1
        assert not conflicts[0].is_conflict

    def test_min_repos_filter(self, tmp_path):
        _make_repo(tmp_path, "repo-a", ["click>=8.1.0"])
        # Only 1 repo, min_repos=2 should filter it out
        all_entries = scan_all(tmp_path)
        index = build_dep_index(all_entries)
        conflicts = find_conflicts(index, min_repos=2)
        assert len(conflicts) == 0


class TestRecommendVersion:
    def test_highest_min(self):
        entries = [
            DepEntry(repo="a", raw="click>=8.0", name="click", specifiers=">=8.0"),
            DepEntry(repo="b", raw="click>=8.1.0", name="click", specifiers=">=8.1.0"),
            DepEntry(repo="c", raw="click>=8.4.0", name="click", specifiers=">=8.4.0"),
        ]
        result = recommend_version(entries)
        assert result == ">=8.4.0"

    def test_upper_bound_preserved(self):
        entries = [
            DepEntry(repo="a", raw="ruff>=0.4.0", name="ruff", specifiers=">=0.4.0"),
            DepEntry(repo="b", raw="ruff>=0.9.0,<1.0", name="ruff", specifiers=">=0.9.0,<1.0"),
        ]
        result = recommend_version(entries)
        assert ">=0.9.0" in result
        assert "<1.0" in result

    def test_empty_entries(self):
        assert recommend_version([]) == ""


class TestGenerateFix:
    def test_fix_map(self):
        entries = [
            DepEntry(repo="a", raw="click>=8.0", name="click", specifiers=">=8.0"),
            DepEntry(repo="b", raw="click>=8.1.0", name="click", specifiers=">=8.1.0"),
        ]
        fixes = generate_fix(entries, ">=8.1.0")
        assert "a" in fixes
        assert fixes["a"] == "click>=8.1.0"
        # b already at recommended, should not be in fixes
        assert "b" not in fixes

    def test_extras_preserved(self):
        entries = [
            DepEntry(repo="a", raw="mcp[server]>=1.0", name="mcp", specifiers=">=1.0", extras=["server"]),
        ]
        fixes = generate_fix(entries, ">=1.5.0")
        assert "a" in fixes
        assert "mcp[server]>=1.5.0" == fixes["a"]


class TestFixer:
    def test_replace_dep_in_text(self):
        from crossrepo_dep_manager.fixer import replace_dep_in_text

        text = '    "click>=8.0",\n'
        result, count = replace_dep_in_text(text, "click", "click>=8.1.0")
        assert count == 1
        assert "click>=8.1.0" in result

    def test_replace_preserves_indent(self):
        from crossrepo_dep_manager.fixer import replace_dep_in_text

        text = '    "rich>=13.0.0",\n'
        result, count = replace_dep_in_text(text, "rich", "rich>=15.0.0")
        assert count == 1
        assert "    " in result

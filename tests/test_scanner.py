"""Tests for cross-repo dependency scanner."""

from __future__ import annotations

from pathlib import Path

from crossrepo_dep_manager.scanner import (
    DepEntry,
    build_dep_index,
    find_conflicts,
    generate_fix,
    recommend_version,
    scan_all,
    scan_repo,
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
        assert fixes["a"] == "mcp[server]>=1.5.0"


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


class TestRecommendVersionCompatibleRelease:
    """~= (compatible-release) specifiers must be treated as a minimum floor."""

    def test_tilde_eq_only(self):
        entries = [
            DepEntry(repo="a", raw="requests~=2.28.0", name="requests", specifiers="~=2.28.0"),
            DepEntry(repo="b", raw="requests~=2.27.0", name="requests", specifiers="~=2.27.0"),
        ]
        result = recommend_version(entries)
        # Should return the higher floor, not ""
        assert result != ""
        assert "2.28" in result

    def test_tilde_eq_mixed_with_ge(self):
        entries = [
            DepEntry(repo="a", raw="requests~=2.28.0", name="requests", specifiers="~=2.28.0"),
            DepEntry(repo="b", raw="requests>=2.25.0", name="requests", specifiers=">=2.25.0"),
        ]
        result = recommend_version(entries)
        assert result != ""
        # 2.28.0 is the higher floor
        assert "2.28" in result

    def test_generate_fix_with_tilde_eq_source(self):
        """generate_fix must produce a fix for a ~= entry when recommended is different."""
        entries = [
            DepEntry(repo="a", raw="requests~=2.27.0", name="requests", specifiers="~=2.27.0"),
            DepEntry(repo="b", raw="requests>=2.28.0", name="requests", specifiers=">=2.28.0"),
        ]
        recommended = ">=2.28.0"
        fixes = generate_fix(entries, recommended)
        # repo "a" has ~=2.27.0 != >=2.28.0, so it should get a fix
        assert "a" in fixes
        assert fixes["a"] == "requests>=2.28.0"
        # repo "b" is already at recommended
        assert "b" not in fixes


class TestFixerMarkerDeduplication:
    """replace_dep_in_text must not duplicate PEP 508 environment markers."""

    def test_marker_not_duplicated_on_update(self):
        from crossrepo_dep_manager.fixer import replace_dep_in_text

        # Simulates a TOML dep string with an environment marker
        text = '    "tomli>=2.0.0; python_version < \'3.11\'",\n'
        # new_raw as generated by generate_fix (includes the marker)
        new_raw = "tomli>=2.0.1; python_version < '3.11'"
        result, count = replace_dep_in_text(text, "tomli", new_raw)
        assert count == 1
        # The marker must appear exactly once
        assert result.count("python_version") == 1
        assert "tomli>=2.0.1" in result

    def test_marker_preserved_when_new_raw_also_has_marker(self):
        from crossrepo_dep_manager.fixer import replace_dep_in_text

        text = '    "packaging>=23.0; python_version >= \'3.8\'",\n'
        new_raw = "packaging>=24.0; python_version >= '3.8'"
        result, count = replace_dep_in_text(text, "packaging", new_raw)
        assert count == 1
        assert result.count("python_version") == 1
        assert "packaging>=24.0" in result

    def test_no_marker_still_works(self):
        from crossrepo_dep_manager.fixer import replace_dep_in_text

        text = '    "click>=8.0",\n'
        result, count = replace_dep_in_text(text, "click", "click>=8.1.0")
        assert count == 1
        assert "click>=8.1.0" in result
        assert ";" not in result


class TestRecommendVersionExactPin:
    """== (exact pin) specifiers must contribute their version as a minimum floor."""

    def test_exact_pin_only_returns_recommendation(self):
        """Two repos with different exact pins → recommend the higher one as >=."""
        entries = [
            DepEntry(repo="a", raw="requests==2.27.0", name="requests", specifiers="==2.27.0"),
            DepEntry(repo="b", raw="requests==2.28.0", name="requests", specifiers="==2.28.0"),
        ]
        result = recommend_version(entries)
        assert result != "", "exact pins should produce a recommendation, not silence"
        assert "2.28" in result

    def test_exact_pin_mixed_with_range(self):
        """A higher exact pin must not be ignored when mixed with a lower >= range."""
        entries = [
            DepEntry(repo="a", raw="requests==2.28.0", name="requests", specifiers="==2.28.0"),
            DepEntry(repo="b", raw="requests>=2.25.0", name="requests", specifiers=">=2.25.0"),
        ]
        result = recommend_version(entries)
        # 2.28.0 is a higher floor than >=2.25.0; recommendation must reflect that
        assert "2.28" in result, f"expected 2.28 floor but got: {result!r}"

    def test_exact_pin_lower_than_range_does_not_lower_floor(self):
        """A lower exact pin must not pull the recommended floor below the >= floor."""
        entries = [
            DepEntry(repo="a", raw="requests==2.20.0", name="requests", specifiers="==2.20.0"),
            DepEntry(repo="b", raw="requests>=2.28.0", name="requests", specifiers=">=2.28.0"),
        ]
        result = recommend_version(entries)
        assert "2.28" in result, f"expected floor >=2.28 but got: {result!r}"

    def test_exact_pin_wildcard_does_not_crash(self):
        """==2.8.* wildcard is not a valid packaging.Version; it must be silently skipped."""
        entries = [
            DepEntry(repo="a", raw="requests==2.8.*", name="requests", specifiers="==2.8.*"),
            DepEntry(repo="b", raw="requests>=2.7.0", name="requests", specifiers=">=2.7.0"),
        ]
        # Wildcard can't be compared; floor comes only from >=2.7.0
        result = recommend_version(entries)
        assert result == ">=2.7.0", f"expected >=2.7.0 but got: {result!r}"

    def test_generate_fix_includes_pinned_repo(self):
        """generate_fix must produce a fix for a == entry when recommended differs."""
        entries = [
            DepEntry(repo="a", raw="requests==2.27.0", name="requests", specifiers="==2.27.0"),
            DepEntry(repo="b", raw="requests>=2.28.0", name="requests", specifiers=">=2.28.0"),
        ]
        recommended = recommend_version(entries)
        fixes = generate_fix(entries, recommended)
        # repo "a" has ==2.27.0 which != recommended, so it must get a fix
        assert "a" in fixes, "pinned repo should be included in fix map"
        assert "2.28" in fixes["a"]
        # repo "b" is already at recommended
        assert "b" not in fixes


class TestFixerApplyFix:
    """apply_fix and apply_all_fixes must correctly read/write pyproject.toml files."""

    def _make_pyproject(self, tmp_path: Path, repo_name: str, dep_line: str) -> Path:
        repo = tmp_path / repo_name
        repo.mkdir()
        content = (
            "[project]\n"
            f'name = "{repo_name}"\n'
            'version = "0.1.0"\n'
            "dependencies = [\n"
            f'    "{dep_line}",\n'
            "]\n"
        )
        (repo / "pyproject.toml").write_text(content, encoding="utf-8")
        return repo

    def test_apply_fix_dry_run_does_not_write(self, tmp_path):
        """dry_run=True: returns True (would change) but must not modify the file."""
        from crossrepo_dep_manager.fixer import apply_fix

        self._make_pyproject(tmp_path, "repo-a", "click>=8.0")
        original = (tmp_path / "repo-a" / "pyproject.toml").read_text()
        changed = apply_fix(tmp_path, "repo-a", "click", "click>=8.1.0", dry_run=True)
        assert changed is True
        after = (tmp_path / "repo-a" / "pyproject.toml").read_text()
        assert after == original, "dry_run must not write to disk"

    def test_apply_fix_writes_updated_version(self, tmp_path):
        """dry_run=False must update the pyproject.toml on disk."""
        from crossrepo_dep_manager.fixer import apply_fix

        self._make_pyproject(tmp_path, "repo-a", "click>=8.0")
        changed = apply_fix(tmp_path, "repo-a", "click", "click>=8.1.0", dry_run=False)
        assert changed is True
        content = (tmp_path / "repo-a" / "pyproject.toml").read_text()
        assert "click>=8.1.0" in content
        # Original spec should not appear (replace >=8.1.0 to avoid false negative)
        assert "click>=8.0" not in content.replace("click>=8.1.0", "")

    def test_apply_fix_missing_repo_returns_false(self, tmp_path):
        """A repo with no pyproject.toml must return False, not raise."""
        from crossrepo_dep_manager.fixer import apply_fix

        result = apply_fix(tmp_path, "nonexistent", "click", "click>=8.1.0", dry_run=False)
        assert result is False

    def test_apply_fix_no_match_returns_false(self, tmp_path):
        """If the dep is not found in pyproject.toml, return False."""
        from crossrepo_dep_manager.fixer import apply_fix

        self._make_pyproject(tmp_path, "repo-a", "rich>=13.0.0")
        changed = apply_fix(tmp_path, "repo-a", "click", "click>=8.1.0", dry_run=False)
        assert changed is False

    def test_apply_all_fixes_multi_repo(self, tmp_path):
        """apply_all_fixes must update only the repos in the fix map."""
        from crossrepo_dep_manager.fixer import apply_all_fixes

        self._make_pyproject(tmp_path, "repo-a", "click>=8.0")
        self._make_pyproject(tmp_path, "repo-b", "click>=8.1.0")
        fixes = {"repo-a": {"click": "click>=8.2.0"}}
        results = apply_all_fixes(tmp_path, fixes, {}, dry_run=False)
        assert len(results) == 1
        assert results[0]["changed"] is True
        assert "click>=8.2.0" in (tmp_path / "repo-a" / "pyproject.toml").read_text()
        # repo-b must be untouched
        assert "click>=8.1.0" in (tmp_path / "repo-b" / "pyproject.toml").read_text()

    def test_apply_all_fixes_dry_run(self, tmp_path):
        """apply_all_fixes with dry_run=True must not write any files."""
        from crossrepo_dep_manager.fixer import apply_all_fixes

        self._make_pyproject(tmp_path, "repo-a", "click>=8.0")
        original = (tmp_path / "repo-a" / "pyproject.toml").read_text()
        fixes = {"repo-a": {"click": "click>=8.2.0"}}
        results = apply_all_fixes(tmp_path, fixes, {}, dry_run=True)
        assert results[0]["changed"] is True  # would change
        assert results[0]["dry_run"] is True
        after = (tmp_path / "repo-a" / "pyproject.toml").read_text()
        assert after == original, "dry_run must not write to disk"

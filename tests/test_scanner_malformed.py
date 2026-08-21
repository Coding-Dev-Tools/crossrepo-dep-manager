"""Tests for scan_repo resilience to malformed pyproject.toml files."""
from __future__ import annotations

from pathlib import Path

from crossrepo_dep_manager.scanner import scan_all, scan_repo


class TestScanRepoMalformed:
    """scan_repo must not crash on malformed pyproject.toml; return empty list instead."""

    def test_malformed_toml_returns_empty(self, tmp_path: Path):
        """A repo with invalid TOML syntax must return [] instead of raising."""
        repo = tmp_path / "broken-repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[project\nname = broken\n", encoding="utf-8")
        result = scan_repo(repo)
        assert result == []

    def test_scan_all_skips_malformed_repo(self, tmp_path: Path):
        """scan_all must continue scanning other repos when one has bad TOML."""
        # Good repo
        good = tmp_path / "good-repo"
        good.mkdir()
        (good / "pyproject.toml").write_text(
            '[project]\nname = "good"\nversion = "0.1.0"\n'
            'dependencies = ["click>=8.0"]\n',
            encoding="utf-8",
        )
        # Bad repo
        bad = tmp_path / "bad-repo"
        bad.mkdir()
        (bad / "pyproject.toml").write_text("not valid toml {{{{", encoding="utf-8")

        results = scan_all(tmp_path)
        assert "good-repo" in results
        assert len(results["good-repo"]) == 1
        # bad-repo should either be absent or have empty entries
        assert results.get("bad-repo", []) == []

    def test_empty_pyproject_returns_empty(self, tmp_path: Path):
        """A zero-byte pyproject.toml must not crash."""
        repo = tmp_path / "empty-repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("", encoding="utf-8")
        result = scan_repo(repo)
        assert result == []

    def test_missing_project_key_returns_empty(self, tmp_path: Path):
        """A valid TOML file with no [project] table must return []."""
        repo = tmp_path / "no-project"
        repo.mkdir()
        (repo / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["hatchling"]\n',
            encoding="utf-8",
        )
        result = scan_repo(repo)
        assert result == []


# --- silent-failure guard: scan errors must be surfaced, not swallowed ---

def test_scan_repo_reports_parse_error(tmp_path):
    from crossrepo_dep_manager.scanner import scan_repo
    (tmp_path / "pyproject.toml").write_text("not [ valid toml {{{", encoding="utf-8")
    errors = []
    entries = scan_repo(tmp_path, errors=errors)
    assert entries == []
    assert len(errors) == 1
    assert errors[0][0] == tmp_path.name
    assert "TOML" in errors[0][1] or "Decode" in errors[0][1] or ":" in errors[0][1]


def test_scan_repo_no_error_on_valid(tmp_path):
    from crossrepo_dep_manager.scanner import scan_repo
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["click>=8.0"]\n', encoding="utf-8"
    )
    errors = []
    entries = scan_repo(tmp_path, errors=errors)
    assert len(entries) == 1
    assert errors == []


def test_scan_repo_backward_compatible_no_errors_arg(tmp_path):
    from crossrepo_dep_manager.scanner import scan_repo
    (tmp_path / "pyproject.toml").write_text("broken [[[", encoding="utf-8")
    assert scan_repo(tmp_path) == []


def test_scan_all_collects_errors(tmp_path):
    from crossrepo_dep_manager.scanner import scan_all
    good = tmp_path / "goodrepo"; good.mkdir()
    (good / "pyproject.toml").write_text(
        '[project]\nname="g"\ndependencies=["click>=8.0"]\n', encoding="utf-8"
    )
    bad = tmp_path / "badrepo"; bad.mkdir()
    (bad / "pyproject.toml").write_text("{{{ nonsense", encoding="utf-8")
    errors = []
    results = scan_all(tmp_path, errors=errors)
    assert "goodrepo" in results
    assert "badrepo" not in results
    assert [r for r, _ in errors] == ["badrepo"]

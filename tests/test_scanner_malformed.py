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

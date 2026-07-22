"""Tests for cross-repo dependency manager CLI."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from crossrepo_dep_manager.cli import app

runner = CliRunner()


def _make_test_repos(tmp_path: Path) -> Path:
    """Create a minimal set of test repos for CLI tests."""
    (tmp_path / "repo-a").mkdir(parents=True)
    (tmp_path / "repo-a" / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
        'dependencies = [\n    "click>=8.0",\n]\n'
    )
    (tmp_path / "repo-b").mkdir(parents=True)
    (tmp_path / "repo-b" / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[project]\nname = "repo-b"\nversion = "0.1.0"\n'
        'dependencies = [\n    "click>=8.1.0",\n]\n'
    )
    (tmp_path / "repo-c").mkdir(parents=True)
    (tmp_path / "repo-c" / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[project]\nname = "repo-c"\nversion = "0.1.0"\n'
    )
    return tmp_path


class TestScanCommand:
    def test_scan_table_default(self, tmp_path):
        repos_dir = _make_test_repos(tmp_path)
        result = runner.invoke(app, ["scan", "--repos-dir", str(repos_dir)])
        assert result.exit_code == 0
        assert "click" in result.stdout
        assert "Total shared deps:" in result.stdout

    def test_scan_json_format(self, tmp_path):
        repos_dir = _make_test_repos(tmp_path)
        result = runner.invoke(app, ["scan", "--repos-dir", str(repos_dir), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        packages = [d["package"] for d in data]
        assert "click" in packages

    def test_scan_min_repos_filter(self, tmp_path):
        repos_dir = _make_test_repos(tmp_path)
        result = runner.invoke(app, ["scan", "--repos-dir", str(repos_dir), "--min-repos", "3"])
        assert result.exit_code == 0
        assert "click" not in result.stdout or "Total shared deps: 0" in result.stdout

    def test_scan_no_repos_dir(self):
        with patch("pathlib.Path.exists", return_value=False):
            result = runner.invoke(app, ["scan"])
        assert result.exit_code == 1
        assert "No repos directory found" in result.stdout

    def test_scan_handles_missing_optional_deps(self, tmp_path):
        _make_test_repos(tmp_path)
        result = runner.invoke(app, ["scan", "--repos-dir", str(tmp_path)])
        assert result.exit_code == 0


class TestConflictsCommand:
    def test_conflicts_shows_only_conflicts(self, tmp_path):
        repos_dir = _make_test_repos(tmp_path)
        result = runner.invoke(app, ["conflicts", "--repos-dir", str(repos_dir)])
        assert result.exit_code == 0
        assert "click" in result.stdout
        assert "Version Conflicts" in result.stdout

    def test_conflicts_no_conflicts(self, tmp_path):
        (tmp_path / "repo-a").mkdir(parents=True)
        (tmp_path / "repo-a" / "pyproject.toml").write_text(
            '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
            'dependencies = [\n    "click>=8.1.0",\n]\n'
        )
        (tmp_path / "repo-b").mkdir(parents=True)
        (tmp_path / "repo-b" / "pyproject.toml").write_text(
            '[project]\nname = "repo-b"\nversion = "0.1.0"\n'
            'dependencies = [\n    "click>=8.1.0",\n]\n'
        )
        result = runner.invoke(app, ["conflicts", "--repos-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No version conflicts found" in result.stdout

    def test_conflicts_single_repo(self, tmp_path):
        (tmp_path / "repo-a").mkdir(parents=True)
        (tmp_path / "repo-a" / "pyproject.toml").write_text(
            '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
            'dependencies = [\n    "click>=8.1.0",\n]\n'
        )
        result = runner.invoke(app, ["conflicts", "--repos-dir", str(tmp_path)])
        assert result.exit_code == 0


class TestFixCommand:
    def test_fix_dry_run_shows_no_apply(self, tmp_path):
        repos_dir = _make_test_repos(tmp_path)
        result = runner.invoke(app, ["fix", "--repos-dir", str(repos_dir)])
        assert result.exit_code == 0
        assert "DRY RUN" in result.stdout
        assert "click" in result.stdout

    def test_fix_apply_flag(self, tmp_path):
        repos_dir = _make_test_repos(tmp_path)
        result = runner.invoke(app, ["fix", "--repos-dir", str(repos_dir), "--apply"])
        assert result.exit_code == 0
        assert "APPLIED" in result.stdout
        content = (repos_dir / "repo-a" / "pyproject.toml").read_text()
        assert "click>=8.1.0" in content

    def test_fix_no_conflicts(self, tmp_path):
        (tmp_path / "repo-a").mkdir(parents=True)
        (tmp_path / "repo-a" / "pyproject.toml").write_text(
            '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
            'dependencies = [\n    "click>=8.1.0",\n]\n'
        )
        result = runner.invoke(app, ["fix", "--repos-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No conflicts to fix" in result.stdout

    def test_fix_with_package_filter(self, tmp_path):
        repos_dir = _make_test_repos(tmp_path)
        (tmp_path / "repo-a" / "pyproject.toml").write_text(
            '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
            'dependencies = [\n    "click>=8.0",\n    "rich>=13.0",\n]\n'
        )
        (tmp_path / "repo-b" / "pyproject.toml").write_text(
            '[project]\nname = "repo-b"\nversion = "0.1.0"\n'
            'dependencies = [\n    "click>=8.1.0",\n    "rich>=14.0",\n]\n'
        )
        result = runner.invoke(app, ["fix", "--repos-dir", str(repos_dir), "--package", "click"])
        assert result.exit_code == 0
        assert "click" in result.stdout


class TestOutdatedCommand:
    def test_outdated_shows_lagging(self, tmp_path):
        repos_dir = _make_test_repos(tmp_path)
        result = runner.invoke(app, ["outdated", "--repos-dir", str(repos_dir)])
        assert result.exit_code == 0
        assert "click" in result.stdout

    def test_outdated_no_issues(self, tmp_path):
        (tmp_path / "repo-a").mkdir(parents=True)
        (tmp_path / "repo-a" / "pyproject.toml").write_text(
            '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
            'dependencies = [\n    "click>=8.1.0",\n]\n'
        )
        result = runner.invoke(app, ["outdated", "--repos-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "consistent" in result.stdout or "All" in result.stdout

    def test_outdated_empty(self, tmp_path):
        (tmp_path / "repo-a").mkdir(parents=True)
        (tmp_path / "repo-a" / "pyproject.toml").write_text(
            '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
        )
        result = runner.invoke(app, ["outdated", "--repos-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "consistent" in result.stdout or "All" in result.stdout


class TestHelpCommand:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "crossrepo-dep" in result.stdout
        assert "scan" in result.stdout
        assert "conflicts" in result.stdout
        assert "fix" in result.stdout
        assert "outdated" in result.stdout

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Pre-commit hooks configuration (ruff, ruff-format, bandit, basic checks)
- Dependabot configuration for automated dependency updates
- CHANGELOG.md for tracking changes

## [0.1.0] - 2026-06-10

### Added
- Initial release of crossrepo-dep-manager
- CLI commands: scan, conflicts, outdated, fix
- Cross-repo dependency scanning and conflict detection
- Automated version recommendation (highest minimum version)
- pyproject.toml fixing with dry-run support
- Support for optional dependencies and extras
- Comprehensive test suite

### Changed
- CI workflow with matrix testing (Python 3.11, 3.12, 3.13)
- Auto-code-review workflow integration
- Publish workflow for PyPI releases

### Fixed
- Lint clean: contextlib.suppress, unused imports, import sorting

## [0.0.1] - 2026-05-31

### Added
- Initial project structure
- Basic scanner and conflict detection
- Initial CLI with typer
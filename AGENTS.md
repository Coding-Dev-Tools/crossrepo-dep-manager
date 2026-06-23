# crossrepo-dep-manager

## Purpose
Cross-repo dependency management CLI for Coding-Dev-Tools. Scans all Python repos in a directory, detects version conflicts in shared dependencies, recommends unified version specs (highest minimum across the fleet), and can apply fixes automatically.

## Build & Test Commands
- Install: `pip install -e .` or `pip install crossrepo-dep-manager`
- Test: `pytest -q`
- Lint: `ruff check . --target-version py310`
- Build: `pip install build twine && python -m build && twine check dist/*`
- CLI check: `crossrepo-dep --help`

## Architecture
Key directories:
- `src/crossrepo_dep_manager/` — Main package (CLI, scanner, conflict detector)
- `tests/` — Test suite
- `.github/workflows/` — CI/CD (auto-code-review.yml, ci.yml, publish.yml)
- `dist/` — Built distributions

## Conventions
- Language: Python 3.10+
- Test framework: pytest
- CI: GitHub Actions (matrix: Python 3.11, 3.12, 3.13)
- Linting: ruff (line-length 120, target py310)
- Build system: hatchling
- Package layout: src/ layout
- Dependencies: click, rich, typer, tomli, packaging
- CLI entry point: crossrepo_dep_manager.cli:app
- Default branch: master
# crossrepo-dep-manager — Agent Instructions

## Purpose
Cross-repo dependency management CLI for Coding-Dev-Tools monorepo. Scans Python repos, detects version conflicts in shared dependencies, recommends unified version specs (highest minimum across the fleet), and applies fixes automatically.

## Repository Structure
```
crossrepo-dep-manager/
├── .github/workflows/
│   ├── ci.yml                    # CI pipeline (test, lint, format)
│   └── auto-code-review.yml      # Automated PR code review
├── src/crossrepo_dep_manager/
│   ├── __init__.py
│   ├── cli.py                    # Typer CLI entry point
│   ├── scanner.py                # Dependency scanning & conflict detection
│   └── fixer.py                  # Applying fixes to pyproject.toml
├── tests/
│   └── test_scanner.py           # Unit tests
├── pyproject.toml                # Project config (hatchling, deps, ruff, pytest)
├── README.md                     # Usage docs
└── .gitignore
```

## Development Commands
```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Run CLI
crossrepo-dep --help
crossrepo-dep scan
crossrepo-dep conflicts
crossrepo-dep fix --dry-run
crossrepo-dep outdated
```

## CI Pipeline
- **Test**: pytest with coverage
- **Lint**: ruff check (E, F, I, W, UP, B, SIM)
- **Format**: ruff format --check

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `cli.py` | Typer CLI: scan, conflicts, fix, outdated commands |
| `scanner.py` | scan_repo, scan_all, build_dep_index, find_conflicts, recommend_version, generate_fix |
| `fixer.py` | replace_dep_in_text, apply_all_fixes (writes to pyproject.toml) |

## Version Conflict Logic
- Conflict = 2+ repos use same package with different version specifiers
- Resolution = highest minimum version (e.g., `>=8.0` vs `>=8.4.0` → recommend `>=8.4.0`)
- Upper bounds preserved (e.g., `>=0.4.0,<1.0` + `>=0.9.0,<1.0` → `>=0.9.0,<1.0`)
- Extras preserved (e.g., `mcp[server]>=1.0` → `mcp[server]>=1.5.0`)

## Safety
- `fix` command is dry-run by default (`--dry-run`)
- Use `--apply` to write changes
- Only modifies `dependencies` and `optional-dependencies` in `pyproject.toml`

## Testing
- 17 unit tests in `tests/test_scanner.py`
- Covers: scan_repo, scan_all, build_dep_index, find_conflicts, recommend_version, generate_fix, fixer
- Run with `python -m pytest tests/ -v`
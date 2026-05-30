# crossrepo-dep-manager

Cross-repo dependency management CLI for Coding-Dev-Tools.

Scans all Python repos in a directory, detects version conflicts in shared
dependencies, recommends unified version specs (highest minimum across the
fleet), and can apply fixes automatically.

## Install

```bash
pip install crossrepo-dep-manager
```

## Commands

### scan — Full dependency report

```bash
crossrepo-dep scan                      # uses ~/rh-repos by default
crossrepo-dep scan --repos-dir /path    # custom repos directory
crossrepo-dep scan --min-repos 3        # only deps used in 3+ repos
crossrepo-dep scan --format json        # machine-readable output
```

### conflicts — Show only version conflicts

```bash
crossrepo-dep conflicts
```

### outdated — Show repos lagging behind fleet max

```bash
crossrepo-dep outdated
```

### fix — Normalize versions (dry-run by default)

```bash
crossrepo-dep fix --dry-run             # preview changes
crossrepo-dep fix --apply               # write changes to pyproject.toml
crossrepo-dep fix --package click       # fix only one package
```

## How it works

1. **Scan** reads every `pyproject.toml` in the repos directory
2. **Index** groups dependencies by package name across repos
3. **Detect** flags packages where different repos pin different minimums
4. **Recommend** picks the highest minimum version (compatible with all repos)
5. **Fix** rewrites pyproject.toml lines to use the recommended spec

## Conflict detection

A conflict is when 2+ repos use the same package but with different version
specifiers. For example:

- repo-a: `click>=8.0`
- repo-b: `click>=8.4.0`

The tool recommends `>=8.4.0` (highest floor) and can update repo-a.

## Safety

- `fix` is dry-run by default — use `--apply` to write changes
- Version upper bounds (like `<2.0`) are preserved in recommendations
- Extras (like `mcp[server]`) are preserved when fixing

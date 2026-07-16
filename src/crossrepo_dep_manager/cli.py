"""CLI for cross-repo dependency management."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from crossrepo_dep_manager.fixer import apply_all_fixes
from crossrepo_dep_manager.scanner import (
    _min_floor,
    build_dep_index,
    find_conflicts,
    generate_fix,
    recommend_version,
    scan_all,
)

app = typer.Typer(
    name="crossrepo-dep",
    help="Cross-repo dependency management for Coding-Dev-Tools",
    no_args_is_help=True,
)
console = Console()


def _repos_dir(repos_dir: str | None) -> Path:
    if repos_dir:
        return Path(repos_dir)
    # Default: ~/rh-repos
    default = Path.home() / "rh-repos"
    if default.exists():
        return default
    console.print("[red]No repos directory found. Use --repos-dir.[/red]")
    raise typer.Exit(1)


@app.command()
def scan(
    repos_dir: str = typer.Option(None, "--repos-dir", help="Path to repos directory"),
    min_repos: int = typer.Option(2, "--min-repos", help="Min repos to consider shared"),
    format: str = typer.Option("table", "--format", help="Output format: table, json"),
) -> None:
    """Scan all repos and report dependency status."""
    rdir = _repos_dir(repos_dir)
    all_entries = scan_all(rdir)
    index = build_dep_index(all_entries)
    conflicts = find_conflicts(index, min_repos=min_repos)

    if format == "json":
        data = []
        for c in conflicts:
            data.append(
                {
                    "package": c.package,
                    "is_conflict": c.is_conflict,
                    "unique_specs": c.unique_specs,
                    "affected_repos": c.affected_repos,
                    "recommended": recommend_version(c.entries),
                }
            )
        console.print_json(json.dumps(data, indent=2))
        return

    # Table output
    table = Table(title="Cross-Repo Dependency Report")
    table.add_column("Package", style="cyan")
    table.add_column("Repos", justify="right")
    table.add_column("Conflict", style="bold")
    table.add_column("Specs")
    table.add_column("Recommended", style="green")

    for c in conflicts:
        conflict_str = "[red]YES[/red]" if c.is_conflict else "[green]no[/green]"
        specs_str = "\n".join(c.unique_specs) if c.is_conflict else c.unique_specs[0] if c.unique_specs else ""
        recommended = recommend_version(c.entries) if c.is_conflict else ""
        table.add_row(
            c.package,
            str(len(c.affected_repos)),
            conflict_str,
            specs_str,
            recommended,
        )

    console.print(table)
    console.print(f"\nTotal shared deps: {len(conflicts)}")
    console.print(f"Conflicts: {sum(1 for c in conflicts if c.is_conflict)}")


@app.command()
def conflicts(
    repos_dir: str = typer.Option(None, "--repos-dir", help="Path to repos directory"),
) -> None:
    """Show only version conflicts across repos."""
    rdir = _repos_dir(repos_dir)
    all_entries = scan_all(rdir)
    index = build_dep_index(all_entries)
    conflicts_list = find_conflicts(index, min_repos=2)

    only_conflicts = [c for c in conflicts_list if c.is_conflict]

    if not only_conflicts:
        console.print("[green]No version conflicts found![/green]")
        return

    table = Table(title="Version Conflicts")
    table.add_column("Package", style="cyan")
    table.add_column("Current Specs", style="red")
    table.add_column("Recommended", style="green")
    table.add_column("Affected Repos")

    for c in only_conflicts:
        recommended = recommend_version(c.entries)
        specs = ", ".join(c.unique_specs)
        repos = ", ".join(c.affected_repos)
        table.add_row(c.package, specs, recommended, repos)

    console.print(table)


@app.command()
def fix(
    repos_dir: str = typer.Option(None, "--repos-dir", help="Path to repos directory"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Preview or apply changes"),
    package: str = typer.Option(None, "--package", "-p", help="Fix only this package"),
) -> None:
    """Fix version conflicts by normalizing to the highest min version."""
    rdir = _repos_dir(repos_dir)
    all_entries = scan_all(rdir)
    index = build_dep_index(all_entries)
    conflicts_list = find_conflicts(index, min_repos=2)
    only_conflicts = [c for c in conflicts_list if c.is_conflict]

    if package:
        only_conflicts = [c for c in only_conflicts if c.package == package]

    if not only_conflicts:
        console.print("[green]No conflicts to fix.[/green]")
        return

    # Build fix map: {repo: {dep_name: new_raw}}
    fix_map: dict[str, dict[str, str]] = {}
    for c in only_conflicts:
        recommended = recommend_version(c.entries)
        if not recommended:
            continue
        fixes = generate_fix(c.entries, recommended)
        for repo, new_raw in fixes.items():
            if repo not in fix_map:
                fix_map[repo] = {}
            fix_map[repo][c.package] = new_raw

    results = apply_all_fixes(rdir, fix_map, index, dry_run=dry_run)

    # Show results
    table = Table(title="Fix Results" + (" (DRY RUN)" if dry_run else " (APPLIED)"))
    table.add_column("Repo", style="cyan")
    table.add_column("Package", style="yellow")
    table.add_column("New Spec", style="green")
    table.add_column("Changed", style="bold")

    for r in results:
        changed_str = "[green]YES[/green]" if r["changed"] else "[dim]no[/dim]"
        table.add_row(r["repo"], r["dep"], r["new"], changed_str)

    console.print(table)

    if dry_run:
        console.print("\n[yellow]This was a dry run. Use --apply to make changes.[/yellow]")


@app.command()
def outdated(
    repos_dir: str = typer.Option(None, "--repos-dir", help="Path to repos directory"),
) -> None:
    """Check for repos with outdated minimum versions relative to the fleet."""
    rdir = _repos_dir(repos_dir)
    all_entries = scan_all(rdir)
    index = build_dep_index(all_entries)
    conflicts_list = find_conflicts(index, min_repos=2)
    only_conflicts = [c for c in conflicts_list if c.is_conflict]

    if not only_conflicts:
        console.print("[green]All shared deps are consistent.[/green]")
        return

    table = Table(title="Outdated Minimum Versions")
    table.add_column("Package", style="cyan")
    table.add_column("Fleet Max", style="green")
    table.add_column("Lagging Repos", style="red")

    for c in only_conflicts:
        recommended = recommend_version(c.entries)
        rec_floor = _min_floor(recommended) if recommended else None
        # A repo is "lagging" only when its minimum floor is strictly below the
        # unified floor. Comparing raw specifier strings (e.g. ">=8.1.0" vs
        # ">=8.1.0,<9.0") would falsely flag compliant repos as lagging.
        lagging = []
        for e in c.entries:
            e_floor = _min_floor(e.specifiers)
            if rec_floor is not None and e_floor is not None and e_floor < rec_floor:
                lagging.append(f"{e.repo} ({e.specifiers})")
        if lagging:
            table.add_row(c.package, recommended, "\n".join(lagging))

    if table.row_count > 0:
        console.print(table)
    else:
        console.print("[green]All repos use the highest minimum version.[/green]")


if __name__ == "__main__":
    app()

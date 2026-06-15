"""Scan and analyze dependencies across multiple Python repos."""

from __future__ import annotations

import contextlib
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from packaging.requirements import Requirement
from packaging.version import Version


@dataclass
class DepEntry:
    """A single dependency declaration in a repo."""

    repo: str
    raw: str
    name: str
    specifiers: str  # e.g. ">=8.1.0"
    extras: list[str] = field(default_factory=list)
    marker: str = ""


@dataclass
class ConflictReport:
    """Version conflict for a shared dependency."""

    package: str
    entries: list[DepEntry]
    unique_specs: list[str]

    @property
    def is_conflict(self) -> bool:
        return len(self.unique_specs) > 1

    @property
    def affected_repos(self) -> list[str]:
        return sorted(set(e.repo for e in self.entries))


def _parse_dep(raw: str) -> tuple[str, str, list[str], str] | None:
    """Parse a PEP 508 dependency string into (name, specifiers, extras, marker)."""
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    try:
        req = Requirement(raw)
    except Exception:
        return None
    name = req.name
    specs = str(req.specifier) if req.specifier else ""
    extras = list(req.extras) if req.extras else []
    marker = str(req.marker) if req.marker else ""
    return name, specs, extras, marker


def scan_repo(repo_path: str | Path) -> list[DepEntry]:
    """Scan a single repo's pyproject.toml for all dependencies."""
    pyproject = Path(repo_path) / "pyproject.toml"
    if not pyproject.exists():
        return []

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    all_raw: list[str] = []
    all_raw.extend(data.get("project", {}).get("dependencies", []))
    for opt_deps in data.get("project", {}).get("optional-dependencies", {}).values():
        all_raw.extend(opt_deps)

    entries: list[DepEntry] = []
    repo_name = Path(repo_path).name
    for raw in all_raw:
        parsed = _parse_dep(raw)
        if parsed is None:
            continue
        name, specs, extras, marker = parsed
        entries.append(DepEntry(
            repo=repo_name,
            raw=raw,
            name=name,
            specifiers=specs,
            extras=extras,
            marker=marker,
        ))
    return entries


def scan_all(repos_dir: str | Path) -> dict[str, list[DepEntry]]:
    """Scan all repos under a directory. Returns {repo_name: [DepEntry]}."""
    repos_dir = Path(repos_dir)
    results: dict[str, list[DepEntry]] = {}
    for child in sorted(repos_dir.iterdir()):
        if child.is_dir() and (child / "pyproject.toml").exists():
            entries = scan_repo(child)
            if entries:
                results[child.name] = entries
    return results


def build_dep_index(all_entries: dict[str, list[DepEntry]]) -> dict[str, list[DepEntry]]:
    """Build a {package_name: [DepEntry]} index across all repos."""
    index: dict[str, list[DepEntry]] = defaultdict(list)
    for _repo, entries in all_entries.items():
        for entry in entries:
            index[entry.name].append(entry)
    return dict(index)


def find_conflicts(index: dict[str, list[DepEntry]], min_repos: int = 3) -> list[ConflictReport]:
    """Find packages used in min_repos+ repos with version spec conflicts."""
    reports: list[ConflictReport] = []
    for name, entries in sorted(index.items()):
        repos = set(e.repo for e in entries)
        if len(repos) < min_repos:
            continue
        unique_specs = sorted(set(e.specifiers for e in entries))
        reports.append(ConflictReport(
            package=name,
            entries=entries,
            unique_specs=unique_specs,
        ))
    return reports


def normalize_version_spec(spec: str) -> str:
    """Normalize a version specifier to a consistent form.

    E.g. '>=8.1.0' and '>=8.1' both refer to the same floor;
    we keep the longer form for precision.
    """
    return spec.strip()


def recommend_version(entries: list[DepEntry]) -> str:
    """Recommend a unified version specifier for a package.

    Strategy: use the highest minimum version across repos,
    preserving the broadest compatible range.
    """
    if not entries:
        return ""

    # Collect all >= specs and find the max
    min_versions: list[Version] = []
    upper_bounds: list[tuple[str, Version]] = []
    for e in entries:
        s = e.specifiers
        for part in s.split(","):
            part = part.strip()
            if part.startswith("~="):
                # Compatible release: ~=x.y.z means >=x.y.z, ==x.y.*
                # Treat the version as a minimum floor.
                with contextlib.suppress(Exception):
                    min_versions.append(Version(part[2:].strip()))
            elif part.startswith(">="):
                with contextlib.suppress(Exception):
                    min_versions.append(Version(part[2:].strip()))
            elif part.startswith(">") and not part.startswith(">="):
                with contextlib.suppress(Exception):
                    min_versions.append(Version(part[1:].strip()))
            elif part.startswith("<") and not part.startswith("<="):
                with contextlib.suppress(Exception):
                    upper_bounds.append(("<", Version(part[1:].strip())))
            elif part.startswith("<="):
                with contextlib.suppress(Exception):
                    upper_bounds.append(("<=", Version(part[2:].strip())))

    if not min_versions:
        return ""

    highest_min = max(min_versions)
    result = f">={highest_min}"

    # Apply upper bounds that are still compatible
    for op, ver in upper_bounds:
        if ver > highest_min:
            result += f",{op}{ver}"

    return result


def generate_fix(entries: list[DepEntry], recommended: str) -> dict[str, str]:
    """Generate a mapping of repo -> new dep string for fixing a conflict."""
    fixes: dict[str, str] = {}
    for e in entries:
        if e.specifiers != recommended:
            new_raw = e.name + recommended
            if e.extras:
                new_raw = f"{e.name}[{','.join(e.extras)}]" + recommended
            if e.marker:
                new_raw += f"; {e.marker}"
            fixes[e.repo] = new_raw
    return fixes

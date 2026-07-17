"""Scan and analyze dependencies across multiple Python repos."""

from __future__ import annotations

import contextlib
import re
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
    recommended: str = ""
    # ``is_conflict`` is computed lazily (see ``_compute_is_conflict``) from the
    # entries + recommended floor, so it is not a plain dataclass field.

    @property
    def is_conflict(self) -> bool:
        return _compute_is_conflict(self.entries, self.recommended)

    @property
    def affected_repos(self) -> list[str]:
        return sorted(set(e.repo for e in self.entries))


def min_floor(specifiers: str) -> Version | None:
    """Highest minimum-version floor expressed by a specifier string.

    Only lower-bounded operators contribute a floor (``>=``, ``~=``,
    ``==``, strict ``>``); upper bounds (``<`` / ``<=``) and exclusions
    (``!=``) do not. Returns ``None`` when no floor can be parsed.
    """
    floor: Version | None = None
    for part in specifiers.split(","):
        part = part.strip()
        if part.startswith(">=") or part.startswith("~=") or part.startswith("=="):
            token = part[2:].strip()
        elif part.startswith(">") and not part.startswith(">="):
            token = part[1:].strip()
        else:
            continue
        try:
            ver = Version(token)
        except Exception:
            continue
        if floor is None or ver > floor:
            floor = ver
    return floor


def _compute_is_conflict(entries: list[DepEntry], recommended: str) -> bool:
    """A conflict is *actionable* only when at least one repo's minimum floor
    is strictly below the unified recommended floor.

    Two specs that are mutually satisfiable (e.g. ``>=8.1.0`` vs
    ``>=8.1.0,<9.0``) share the same floor, so no repo needs raising — they
    are NOT a conflict even though their raw strings differ. This prevents the
    scanner from reporting false conflicts and the fixer from rewriting a valid
    broader spec into a narrower one just to match spelling.
    """
    if not recommended:
        return False
    rec_floor = min_floor(recommended)
    if rec_floor is None:
        return False
    for e in entries:
        f = min_floor(e.specifiers)
        if f is not None and f < rec_floor:
            return True
    return False


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
        entries.append(
            DepEntry(
                repo=repo_name,
                raw=raw,
                name=name,
                specifiers=specs,
                extras=extras,
                marker=marker,
            )
        )
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
    """Find packages used in min_repos+ repos with *actionable* version conflicts.

    A conflict is actionable only when some repo's minimum version floor is
    strictly below the unified recommended floor (see ``_compute_is_conflict``).
    Mutually-satisfiable specs that merely differ in spelling (e.g. operator
    order or a redundant upper bound) are not reported as conflicts.
    """
    reports: list[ConflictReport] = []
    for name, entries in sorted(index.items()):
        repos = set(e.repo for e in entries)
        if len(repos) < min_repos:
            continue
        unique_specs = sorted(set(e.specifiers for e in entries))
        recommended = recommend_version(entries)
        reports.append(
            ConflictReport(
                package=name,
                entries=entries,
                unique_specs=unique_specs,
                recommended=recommended,
            )
        )
    return reports


def normalize_version_spec(spec: str) -> str:
    """Canonicalize a version specifier string.

    - strips surrounding whitespace
    - splits on commas into (operator, version) parts
    - drops empty parts
    - re-emits parts in a stable operator-precedence order so that two
      specifiers differing only in comma ordering (``>=8.1.0,<9.0`` vs
      ``<9.0,>=8.1.0``) compare equal after normalization.

    Unrecognized tokens (no leading comparison operator) are preserved
    verbatim so callers can still reason about them.
    """
    spec = spec.strip()
    if not spec:
        return ""
    precedence = {">=": 0, ">": 1, "==": 2, "~=": 3, "<=": 4, "<": 5, "!=": 6}
    parts: list[tuple[int, str, str]] = []
    for raw in spec.split(","):
        raw = raw.strip()
        if not raw:
            continue
        m = re.match(r"(>=|<=|==|~=|!=|>|<)\s*([^\s,]+)", raw)
        if not m:
            parts.append((99, raw, raw))
            continue
        op, ver = m.group(1), m.group(2)
        parts.append((precedence.get(op, 10), ver, f"{op}{ver}"))
    parts.sort(key=lambda p: (p[0], p[1]))
    return ",".join(p[2] for p in parts)


def recommend_version(entries: list[DepEntry]) -> str:
    """Recommend a unified version specifier for a package.

    Strategy: use the highest minimum version across repos,
    preserving the broadest compatible range.

    Supported specifier forms and how they contribute:
    - ``>=X``   → floor at X
    - ``~=X.Y`` → compatible-release floor at X.Y (treated as >=X.Y)
    - ``>X``    → floor at X (strict; recommendation promotes to >=X)
    - ``==X``   → exact pin; contributes X as a floor so that a repo pinned to
                  a higher version than others raises the fleet minimum correctly.
                  Wildcard pins (``==2.8.*``) cannot be parsed as a Version and
                  are silently skipped.
    - ``<X`` / ``<=X`` → upper bound; preserved in output when compatible
    - ``!=X``   → exclusion; ignored (not representable as a simple range)
    """
    if not entries:
        return ""

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
            elif part.startswith("=="):
                # Exact pin: contributes its version as a minimum floor.
                # Wildcard pins (==2.8.*) raise InvalidVersion and are skipped.
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
    recommended_norm = normalize_version_spec(recommended)
    # A blank recommendation means no safe unified spec could be computed
    # (e.g. every entry uses only upper bounds / exclusions). Emitting
    # ``name + ""`` would write a version-less dependency and corrupt the
    # pyproject.toml, so bail out instead of producing an invalid fix.
    if not recommended_norm:
        return fixes
    for e in entries:
        if normalize_version_spec(e.specifiers) == recommended_norm:
            continue
        new_raw = e.name + recommended
        if e.extras:
            new_raw = f"{e.name}[{','.join(e.extras)}]" + recommended
        if e.marker:
            new_raw += f"; {e.marker}"
        fixes[e.repo] = new_raw
    return fixes

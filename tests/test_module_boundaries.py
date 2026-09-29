"""INV-11 / INV-12 AST boundary enforcement (docs/04_ARCHITECTURE.md §4.2, U04).

Walks every module's source with `ast` and asserts that:
1. Only the twelve documented modules exist under src/ (a new folder means the
   dependency arrows were not updated — this is the case import-linter misses).
2. No module imports a sibling module except through `<sibling>.api`.
3. Every sibling import follows one of the §3 arrows.
4. The observed dependency graph is acyclic.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

# The twelve modules (docs/04_ARCHITECTURE.md §2).
MODULES = frozenset(
    {
        "core",
        "accounts",
        "credentials",
        "sources",
        "pipelines",
        "jobs",
        "youtube",
        "delivery",
        "media",
        "worker",
        "ops",
        "ui",
    }
)

# Allowed sibling imports: importer -> imported (docs/04_ARCHITECTURE.md §2/§3).
# Mirrors the §2 "May import" column exactly; §3's ASCII diagram abbreviates
# `core`/`accounts` (every domain module takes both) and `delivery`'s row.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "ui": MODULES - {"ui"},
    "worker": frozenset({"core", "accounts", "jobs", "media", "delivery"}),
    "delivery": frozenset({"core", "accounts", "youtube", "jobs"}),
    "youtube": frozenset({"core", "accounts", "credentials"}),
    "media": frozenset({"core", "accounts"}),
    "jobs": frozenset({"core", "accounts"}),
    "sources": frozenset({"core", "accounts"}),
    "pipelines": frozenset({"core", "accounts"}),
    "ops": frozenset({"core", "accounts"}),
    "credentials": frozenset({"core", "accounts"}),
    "accounts": frozenset({"core"}),
    "core": frozenset(),
}


def _module_files() -> list[tuple[str, Path]]:
    found = []
    for module in sorted(MODULES):
        base = SRC / module
        if not base.is_dir():
            continue
        for py_file in base.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            found.append((module, py_file))
    return found


def _sibling_imports(module: str, py_file: Path) -> list[tuple[str, str, int]]:
    """Return (imported_sibling, dotted_path, lineno) for cross-module imports."""
    tree = ast.parse(
        py_file.read_text(encoding="utf-8"), filename=str(py_file)
    )
    hits: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative import: stays inside the module
                continue
            dotted = node.module or ""
            parts = dotted.split(".")
            if parts and parts[0] in MODULES and parts[0] != module:
                hits.append((parts[0], dotted, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts and parts[0] in MODULES and parts[0] != module:
                    hits.append((parts[0], alias.name, node.lineno))
    return hits


def test_only_documented_modules_exist_under_src():
    """A new directory under src/ is a new module and must be documented first."""
    on_disk = {
        p.name
        for p in SRC.iterdir()
        if p.is_dir()
        and not p.name.startswith((".", "__", "test"))
        and any(p.rglob("*.py"))
    }
    undocumented = on_disk - MODULES
    assert not undocumented, (
        f"Undocumented module(s) under src/: {sorted(undocumented)}. "
        "Add them to docs/04_ARCHITECTURE.md §2/§3 first, then to this test."
    )


def test_sibling_imports_use_api_only_and_follow_arrows():
    """INV-12: cross-module access is only via `<module>.api`, along §2/§3 arrows."""
    violations: list[str] = []
    for module, py_file in _module_files():
        for sibling, dotted, lineno in _sibling_imports(module, py_file):
            rel = py_file.relative_to(SRC.parent)
            if not (dotted == f"{sibling}.api" or dotted.startswith(f"{sibling}.api.")):
                violations.append(
                    f"{rel}:{lineno} imports '{dotted}' — only '{sibling}.api' "
                    "is a published boundary (INV-12)."
                )
            if sibling not in ALLOWED_IMPORTS[module]:
                violations.append(
                    f"{rel}:{lineno} imports '{sibling}' from '{module}' — "
                    "forbidden by the dependency arrows (docs/04 §2/§3)."
                )
    assert not violations, "\n".join(violations)


def test_dependency_graph_is_acyclic():
    """No cycles, ever (docs/04 §3): a cycle means two modules are really one."""
    graph: dict[str, set[str]] = defaultdict(set)
    indegree = {m: 0 for m in MODULES}
    for module, py_file in _module_files():
        for sibling, _dotted, _lineno in _sibling_imports(module, py_file):
            if sibling not in graph[module]:
                graph[module].add(sibling)
                indegree[sibling] += 1

    queue = deque(m for m in MODULES if indegree[m] == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for dep in graph[current]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                queue.append(dep)

    assert visited == len(MODULES), (
        "Dependency cycle detected among modules: "
        f"{sorted(m for m in MODULES if indegree[m] > 0)}"
    )


def test_core_imports_no_sibling_module():
    """INV-12 / docs/04 §3: `core` imports nothing — dependent on nobody."""
    violations: list[str] = []
    for module, py_file in _module_files():
        if module != "core":
            continue
        for sibling, dotted, lineno in _sibling_imports("core", py_file):
            violations.append(
                f"{py_file.relative_to(SRC.parent)}:{lineno} imports '{dotted}' "
                f"from core — core must import nothing (sibling: {sibling})."
            )
    assert not violations, "\n".join(violations)

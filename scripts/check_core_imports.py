from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "telegram",
    "fastapi",
    "jobs",
    "requests",
    "sqlite",
    "adapters",
    "services",
)
FORBIDDEN_EXACT = {"os.getenv"}


def iter_py_files(root: Path):
    for path in root.rglob("*.py"):
        yield path


def check_file(path: Path) -> list[str]:
    issues: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith(FORBIDDEN_PREFIXES):
                    issues.append(f"{path}:{node.lineno} forbidden import {name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(FORBIDDEN_PREFIXES):
                issues.append(f"{path}:{node.lineno} forbidden import from {module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                full = f"{node.func.value.id}.{node.func.attr}"
                if full in FORBIDDEN_EXACT:
                    issues.append(f"{path}:{node.lineno} forbidden call {full}")
    return issues


def main() -> int:
    root = Path("core")
    all_issues: list[str] = []
    for file in iter_py_files(root):
        all_issues.extend(check_file(file))
    if all_issues:
        print("\n".join(all_issues))
        return 1
    print("core import boundary check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

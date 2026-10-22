"""Ověří, že každá česká hláška v backendu má anglický překlad v app/i18n.py.

Spuštění (v adresáři backend):  python ../tools/check_backend_i18n.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from app.i18n import tr  # noqa: E402

CZECH = re.compile(r"[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]")
LOG_METHODS = {"debug", "info", "warning", "error", "exception"}
# Texty, které se uživateli nezobrazují jako hláška (např. výchozí názvy z NVR).
IGNORED = {"Kamera {channel}", "HDD {disk_id}", "NAS {disk_id}"}


def template(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for index, value in enumerate(node.values):
            if isinstance(value, ast.Constant):
                out.append(value.value)
            else:
                name = re.sub(r"\W+", "_", ast.unparse(value.value)).strip("_") or f"p{index}"
                out.append("{" + name + "}")
        return "".join(out)
    return None


def candidates(path: Path):
    tree = ast.parse(path.read_text())
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skip.add(id(first.value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS:
            skip.update(id(n) for n in ast.walk(node))
        if isinstance(node, ast.JoinedStr):
            skip.update(id(v) for v in node.values)
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        text = template(node)
        if text and CZECH.search(text):
            yield node.lineno, text


def sample(text: str) -> str:
    return re.sub(r"\{[^}]*\}", "X1", text)


def main() -> int:
    missing = []
    for path in sorted(Path("app").rglob("*.py")):
        if path.name == "i18n.py":
            continue
        for line, text in candidates(path):
            if text in IGNORED or "{tr_" in text:
                # f-string, jehož české části se už překládají přes tr()
                continue
            # Úlomek spojovaný s hodnotou ('kód ' + code) se ověří i s doplněnou hodnotou.
            variants = [sample(text)] + ([sample(text) + "X1"] if text.endswith(" ") else [])
            if not any(not CZECH.search(tr(v, "en")) and tr(v, "en") != v for v in variants):
                missing.append(f"{path}:{line}: {text!r}")
    for item in missing:
        print("chybí překlad:", item)
    print(f"{'OK' if not missing else 'CHYBA'} – zkontrolováno, chybějících: {len(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

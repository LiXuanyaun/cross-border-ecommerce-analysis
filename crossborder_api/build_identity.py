"""Stable workspace fingerprint used to reject stale local server processes."""
from __future__ import annotations

import hashlib
from pathlib import Path


def current_build_fingerprint(root: str | Path) -> str:
    root = Path(root).resolve()
    files: list[Path] = []
    for directory, patterns in (
        (root / "crossborder_api", ("*.py",)),
        (root / "crossborder_analytics", ("*.py", "*.sql")),
        (root / "frontend" / "src", ("*.ts", "*.tsx", "*.css")),
    ):
        if not directory.is_dir():
            continue
        for pattern in patterns:
            files.extend(directory.rglob(pattern))
    files.extend(
        path
        for path in (
            root / "frontend" / "package.json",
            root / "frontend" / "package-lock.json",
            root / "frontend" / "dist" / "index.html",
        )
        if path.is_file()
    )
    digest = hashlib.sha256()
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:20]

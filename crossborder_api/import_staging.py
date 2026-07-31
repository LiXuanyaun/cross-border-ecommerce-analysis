from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import uuid

from .import_preview import UploadedFilePayload


STAGING_ROOT = Path(__file__).resolve().parents[1] / ".cache" / "import-staging"


@dataclass(frozen=True)
class StagedImport:
    preview_id: str
    expires_at: str


class ImportStagingStore:
    def __init__(self, root: Path = STAGING_ROOT) -> None:
        self.root = root
        self.ttl_seconds = max(60, int(os.getenv("CROSSBORDER_IMPORT_STAGE_TTL_SECONDS", "3600")))

    def stage(self, payloads: list[UploadedFilePayload]) -> StagedImport:
        self.cleanup_expired()
        preview_id = "preview_{}".format(uuid.uuid4().hex)
        directory = self.root / preview_id
        directory.mkdir(parents=True, exist_ok=False)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        files = []
        for index, payload in enumerate(payloads):
            storage_name = "{:04d}.bin".format(index)
            (directory / storage_name).write_bytes(payload.content)
            files.append({
                "filename": payload.filename,
                "selected_sheet": payload.selected_sheet,
                "storage_name": storage_name,
            })
        (directory / "manifest.json").write_text(json.dumps({
            "preview_id": preview_id,
            "expires_at": expires_at.isoformat(),
            "files": files,
        }, ensure_ascii=False), encoding="utf-8")
        return StagedImport(preview_id, expires_at.isoformat())

    def load(self, preview_id: str) -> list[UploadedFilePayload]:
        directory = self._directory(preview_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("预检引用不存在或已清理，请重新预检")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expires_at = datetime.fromisoformat(str(manifest["expires_at"]))
        if expires_at <= datetime.now(timezone.utc):
            self.delete(preview_id)
            raise FileNotFoundError("预检引用已过期，请重新预检")
        return [
            UploadedFilePayload(
                filename=str(item["filename"]),
                content=(directory / str(item["storage_name"])).read_bytes(),
                selected_sheet=item.get("selected_sheet"),
            )
            for item in manifest.get("files", [])
        ]

    def delete(self, preview_id: str) -> None:
        directory = self._directory(preview_id)
        if directory.exists():
            shutil.rmtree(directory)

    def cleanup_expired(self) -> None:
        if not self.root.exists():
            return
        now = datetime.now(timezone.utc)
        for directory in self.root.iterdir():
            if not directory.is_dir() or not directory.name.startswith("preview_"):
                continue
            manifest_path = directory / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                expired = datetime.fromisoformat(str(manifest["expires_at"])) <= now
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                expired = True
            if expired:
                shutil.rmtree(directory)

    def _directory(self, preview_id: str) -> Path:
        if not preview_id.startswith("preview_") or not preview_id[8:].isalnum():
            raise ValueError("无效的预检引用")
        directory = (self.root / preview_id).resolve()
        root = self.root.resolve()
        if directory.parent != root:
            raise ValueError("无效的预检引用")
        return directory

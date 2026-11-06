"""Resolve Kiro session titles from local workspace state stores."""
from __future__ import annotations

import glob
import json
import logging
import os
from pathlib import Path
import sqlite3
from urllib.parse import unquote, urlparse


class SessionTitleResolver:
    """Cache titles from Kiro's modern SQLite and legacy JSON stores."""

    def __init__(
        self,
        workspace_storage_dir: str | os.PathLike[str] | None = None,
        legacy_sessions_dir: str | os.PathLike[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        kiro_user_dir = (
            Path.home() / "Library" / "Application Support" / "Kiro" / "User"
        )
        self.workspace_storage_dir = Path(
            workspace_storage_dir or kiro_user_dir / "workspaceStorage"
        ).expanduser()
        self.legacy_sessions_dir = Path(
            legacy_sessions_dir
            or kiro_user_dir / "globalStorage" / "kiro.kiroagent" / "workspace-sessions"
        ).expanduser()
        self.logger = logger or logging.getLogger(__name__)
        self._modern_cache: dict[str, tuple[tuple[int, ...], dict[str, str], dict[str, str]]] = {}
        self._legacy_cache: dict[str, tuple[tuple[int, ...], dict[str, str], dict[str, str]]] = {}
        self._titles: dict[str, str] = {}
        self._workspaces: dict[str, str] = {}

    def refresh(self, force: bool = False) -> bool:
        """Refresh changed files and return whether the merged mappings changed."""
        modern_paths = set(
            glob.glob(str(self.workspace_storage_dir / "*" / "state.vscdb"))
        )
        legacy_paths = set(glob.glob(str(self.legacy_sessions_dir / "*" / "sessions.json")))
        self._drop_deleted(self._modern_cache, modern_paths)
        self._drop_deleted(self._legacy_cache, legacy_paths)

        for path in sorted(modern_paths):
            fingerprint = self._db_fingerprint(Path(path))
            if fingerprint is None:
                continue
            cached = self._modern_cache.get(path)
            if not force and cached is not None and cached[0] == fingerprint:
                continue
            loaded = self._read_modern(Path(path))
            if loaded is not None:
                self._modern_cache[path] = (fingerprint, *loaded)

        for path in sorted(legacy_paths):
            fingerprint = self._file_fingerprint(Path(path))
            if fingerprint is None:
                continue
            cached = self._legacy_cache.get(path)
            if not force and cached is not None and cached[0] == fingerprint:
                continue
            loaded = self._read_legacy(Path(path))
            if loaded is not None:
                self._legacy_cache[path] = (fingerprint, *loaded)

        titles: dict[str, str] = {}
        workspaces: dict[str, str] = {}
        for _, source_titles, source_workspaces in self._legacy_cache.values():
            titles.update(source_titles)
            workspaces.update(source_workspaces)
        # Modern titles take precedence. Empty modern workspace paths do not erase
        # a useful path retained by a legacy entry for the same session.
        for _, source_titles, source_workspaces in self._modern_cache.values():
            titles.update(source_titles)
            workspaces.update(source_workspaces)

        changed = titles != self._titles or workspaces != self._workspaces
        self._titles = titles
        self._workspaces = workspaces
        return changed

    def title_for(self, session_id: str) -> str:
        return self._titles.get(self._canonical_id(session_id), "")

    def workspace_for(self, session_id: str) -> str:
        return self._workspaces.get(self._canonical_id(session_id), "")

    def titles(self) -> dict[str, str]:
        return dict(self._titles)

    @staticmethod
    def _drop_deleted(cache: dict, paths: set[str]) -> None:
        for stale in set(cache) - paths:
            cache.pop(stale, None)

    @staticmethod
    def _canonical_id(value: object) -> str:
        session_id = str(value or "").strip()
        if not session_id:
            return ""
        return session_id if session_id.startswith("sess_") else f"sess_{session_id}"

    @staticmethod
    def _clean_title(value: object) -> str:
        return " ".join(str(value or "").split())[:100]

    @staticmethod
    def _stat_fingerprint(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    def _file_fingerprint(self, path: Path) -> tuple[int, ...] | None:
        try:
            return self._stat_fingerprint(path)
        except OSError as exc:
            self.logger.debug("读取会话标题文件状态失败 %s: %s", path, exc)
            return None

    def _db_fingerprint(self, path: Path) -> tuple[int, ...] | None:
        try:
            database = self._stat_fingerprint(path)
            wal_path = Path(f"{path}-wal")
            wal = self._stat_fingerprint(wal_path) if wal_path.exists() else (0, 0)
            workspace_json = path.parent / "workspace.json"
            workspace = (
                self._stat_fingerprint(workspace_json) if workspace_json.exists() else (0, 0)
            )
            return (*database, *wal, *workspace)
        except OSError as exc:
            self.logger.debug("读取 Kiro 状态库状态失败 %s: %s", path, exc)
            return None

    def _read_modern(self, path: Path) -> tuple[dict[str, str], dict[str, str]] | None:
        connection = None
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=0.15
            )
            row = connection.execute(
                "SELECT value FROM ItemTable WHERE key = ?", ("kiro.kiroAgent",)
            ).fetchone()
            if row is None:
                return {}, {}
            raw = row[0]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if not isinstance(raw, str):
                return {}, {}
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return {}, {}
            entries = payload.get("sessionPanels.entries")
            if not isinstance(entries, list):
                panels = payload.get("sessionPanels", {})
                entries = panels.get("entries", []) if isinstance(panels, dict) else []
            workspace = self._modern_workspace(path.parent / "workspace.json")
            titles: dict[str, str] = {}
            workspaces: dict[str, str] = {}
            for item in entries if isinstance(entries, list) else []:
                if not isinstance(item, dict):
                    continue
                session_id = self._canonical_id(item.get("id"))
                title = self._clean_title(item.get("title"))
                if not session_id or not title:
                    continue
                titles[session_id] = title
                if workspace:
                    workspaces[session_id] = workspace
            return titles, workspaces
        except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, TypeError) as exc:
            # Kiro can update the database and WAL while this background reader is
            # scanning. Preserve the last good cache and retry on the next refresh.
            self.logger.debug("读取 Kiro 会话标题失败 %s: %s", path, exc)
            return None
        finally:
            if connection is not None:
                connection.close()

    def _modern_workspace(self, path: Path) -> str:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            folder = payload.get("folder", "") if isinstance(payload, dict) else ""
            if not isinstance(folder, str) or not folder:
                return ""
            parsed = urlparse(folder)
            if parsed.scheme == "file":
                value = unquote(parsed.path)
                if parsed.netloc and parsed.netloc not in ("", "localhost"):
                    value = f"//{parsed.netloc}{value}"
                return value
            return unquote(folder)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.logger.debug("读取 Kiro 工作区信息失败 %s: %s", path, exc)
            return ""

    def _read_legacy(self, path: Path) -> tuple[dict[str, str], dict[str, str]] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                entries = payload
            elif isinstance(payload, dict):
                entries = payload.get("sessions", [])
            else:
                entries = []
            titles: dict[str, str] = {}
            workspaces: dict[str, str] = {}
            for item in entries if isinstance(entries, list) else []:
                if not isinstance(item, dict):
                    continue
                session_id = self._canonical_id(item.get("sessionId"))
                title = self._clean_title(item.get("title"))
                if not session_id or not title:
                    continue
                titles[session_id] = title
                workspace = str(item.get("workspaceDirectory") or "").strip()
                if workspace:
                    workspaces[session_id] = workspace
            return titles, workspaces
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
            self.logger.debug("读取旧版 Kiro 会话标题失败 %s: %s", path, exc)
            return None

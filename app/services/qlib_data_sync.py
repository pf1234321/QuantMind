"""investment_data Qlib 完整快照检测、下载、校验和安全切换服务。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import tarfile
import tempfile
from pathlib import PurePosixPath
import threading
import urllib.request
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.database import execute_query, execute_update

SOURCE = "chenditc/investment_data"
RELEASES_API = "https://api.github.com/repos/chenditc/investment_data/releases/latest"
QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_data"
ARCHIVE_NAME = "qlib_bin.tar.gz"
MANIFEST_NAME = "qlib_bin.manifest.json"
_sync_lock = threading.Lock()


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "QuantMind"})
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=120, context=_ssl_context()) as response:  # noqa: S310
            with partial.open("wb") as output:
                shutil.copyfileobj(response, output)
                output.flush()
                os.fsync(output.fileno())
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def _safe_extract(tar: tarfile.TarFile, destination: Path) -> None:
    destination_resolved = destination.resolve()
    for member in tar.getmembers():
        member_path = PurePosixPath(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"Qlib归档包含不安全路径: {member.name}")
        target = (destination / Path(*member_path.parts)).resolve()
        if target != destination_resolved and destination_resolved not in target.parents:
            raise ValueError(f"Qlib归档路径越界: {member.name}")
    tar.extractall(destination)


def _json_request(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "QuantMind"})
    with urllib.request.urlopen(request, timeout=30, context=_ssl_context()) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_from_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    for part in (text[:10], text.replace(".", "-")[:10]):
        try:
            return date.fromisoformat(part).isoformat()
        except ValueError:
            continue
    return None


def _calendar_dates(root: Path) -> tuple[str | None, str | None]:
    candidates = [root / "calendars" / "day.txt", root / "calendars" / "day.bin"]
    for path in candidates:
        if not path.exists() or path.suffix != ".txt":
            continue
        values = [_date_from_value(line.strip()) for line in path.read_text(errors="ignore").splitlines()]
        values = [value for value in values if value]
        if values:
            return min(values), max(values)
    raise ValueError(f"Qlib交易日历不存在或无法读取: {root / 'calendars'}")


def _find_asset(assets: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for asset in assets:
        if asset.get("name") == name:
            return asset
    raise ValueError(f"远程Release缺少必需文件: {name}")


def _asset_digest(asset: dict[str, Any]) -> str | None:
    digest = asset.get("digest")
    if isinstance(digest, str) and digest.lower().startswith("sha256:"):
        return digest.split(":", 1)[1].lower()
    return None


def _manifest_hash(manifest: dict[str, Any], name: str) -> str | None:
    for key in ("sha256", "sha256sum", "checksum"):
        value = manifest.get(key)
        if isinstance(value, str) and len(value) == 64:
            return value.lower()
    files = manifest.get("files")
    if isinstance(files, dict):
        item = files.get(name)
        if isinstance(item, dict):
            return _manifest_hash(item, name)
        if isinstance(item, str) and len(item) == 64:
            return item.lower()
    return None


class QlibDataSyncService:
    def local_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {"data_path": str(QLIB_DIR), "exists": QLIB_DIR.exists(), "valid": False, "min_date": None, "max_date": None}
        if not QLIB_DIR.exists():
            return result
        try:
            result["min_date"], result["max_date"] = _calendar_dates(QLIB_DIR)
            result["valid"] = True
        except (OSError, ValueError) as exc:
            result["error"] = str(exc)
        snapshot = execute_query("SELECT * FROM qlib_data_snapshot WHERE is_current=1 ORDER BY activated_at DESC LIMIT 1")
        if snapshot:
            result.update({"snapshot_id": snapshot[0].get("snapshot_id"), "release_tag": snapshot[0].get("release_tag"), "archive_sha256": snapshot[0].get("archive_sha256"), "manifest_sha256": snapshot[0].get("manifest_sha256")})
        return result

    def remote_status(self) -> dict[str, Any]:
        release = _json_request(RELEASES_API)
        assets = release.get("assets") or []
        archive = _find_asset(assets, ARCHIVE_NAME)
        manifest_asset = _find_asset(assets, MANIFEST_NAME)
        manifest = _json_request(manifest_asset["browser_download_url"])
        remote_date = manifest.get("data_end_date") or manifest.get("end_date") or manifest.get("max_trade_date")
        return {"release_tag": release.get("tag_name"), "release_url": release.get("html_url"), "published_at": release.get("published_at"), "archive": archive, "manifest": manifest_asset, "manifest_data": manifest, "archive_sha256": _manifest_hash(manifest, ARCHIVE_NAME) or _asset_digest(archive), "manifest_sha256": _manifest_hash(manifest, MANIFEST_NAME) or _asset_digest(manifest_asset), "data_start_date": _date_from_value(manifest.get("data_start_date") or manifest.get("start_date")), "data_end_date": _date_from_value(remote_date)}

    def status(self) -> dict[str, Any]:
        local = self.local_status()
        try:
            remote = self.remote_status()
            if remote.get("data_end_date") is None:
                remote["data_end_date"] = local.get("max_date")
            if not local["valid"]:
                reason = "local_data_missing" if not local["exists"] else "local_data_invalid"
            elif local.get("release_tag") == remote.get("release_tag") and local.get("manifest_sha256") == remote.get("manifest_sha256"):
                reason = "already_latest"
            elif local.get("max_date") == remote.get("data_end_date"):
                reason = "historical_revision"
            else:
                reason = "update_required"
            return {"source": SOURCE, "local_qlib_last_date": local.get("max_date"), "remote_qlib_last_date": remote.get("data_end_date"), "local": local, "remote": remote, "sync_required": reason not in ("already_latest",), "sync_reason": reason, "checked_at": datetime.now().isoformat(timespec="seconds")}
        except Exception as exc:  # noqa: BLE001
            return {"source": SOURCE, "local_qlib_last_date": local.get("max_date"), "local": local, "remote": None, "sync_required": False, "sync_reason": "remote_metadata_invalid", "error": str(exc), "checked_at": datetime.now().isoformat(timespec="seconds")}

    def start(self, force: bool = False, sync_mode: str = "manual") -> dict[str, Any]:
        sync_id = f"qlib-sync-{uuid.uuid4().hex}"
        execute_update("INSERT INTO qlib_data_sync_run (sync_run_id, data_source, sync_mode, status, current_stage, progress, target_path) VALUES (%s,%s,%s,'queued','queued',0,%s)", (sync_id, SOURCE, sync_mode, str(QLIB_DIR)))
        thread = threading.Thread(target=self._run, args=(sync_id, force), daemon=True)
        thread.start()
        return {"sync_run_id": sync_id, "status": "queued"}

    def _update(self, sync_id: str, status: str | None = None, stage: str | None = None, progress: int | None = None, **fields: Any) -> None:
        sets, values = [], []
        if status is not None: sets.append("status=%s"); values.append(status)
        if stage is not None: sets.append("current_stage=%s"); values.append(stage)
        if progress is not None: sets.append("progress=%s"); values.append(progress)
        for name, value in fields.items(): sets.append(f"{name}=%s"); values.append(value)
        if status == "running": sets.append("started_at=COALESCE(started_at,NOW())")
        if status in ("success", "failed", "cancelled", "skipped"): sets.append("finished_at=NOW()")
        if sets:
            values.append(sync_id); execute_update(f"UPDATE qlib_data_sync_run SET {', '.join(sets)} WHERE sync_run_id=%s", values)

    def _log(self, sync_id: str, level: str, message: str, stage: str | None = None) -> None:
        execute_update("INSERT INTO qlib_data_sync_log (sync_run_id, stage, level, message) VALUES (%s,%s,%s,%s)", (sync_id, stage, level, message))

    def _run(self, sync_id: str, force: bool) -> None:
        if not _sync_lock.acquire(blocking=False):
            self._update(sync_id, "skipped", "lock", 100, error_message="已有其他Qlib数据同步任务运行")
            return
        try:
            self._update(sync_id, "running", "remote_release", 5)
            self._log(sync_id, "info", "开始检查本地 Qlib 数据和远程 Release", "remote_release")
            status = self.status()
            remote = status.get("remote") or {}
            if not force and not status.get("sync_required"):
                self._log(sync_id, "info", "本地 Qlib 数据已是远程最新版本，无需下载", "already_latest")
                self._update(sync_id, "skipped", "already_latest", 100, remote_last_date=remote.get("data_end_date"), remote_release_tag=remote.get("release_tag"))
                return

            self._update(sync_id, stage="download_manifest", progress=15, remote_last_date=remote.get("data_end_date"), remote_release_tag=remote.get("release_tag"))
            self._log(sync_id, "info", f"发现远程 Release {remote.get('release_tag')}，开始下载 manifest", "download_manifest")
            with tempfile.TemporaryDirectory(prefix="quantmind-qlib-") as temporary:
                temp = Path(temporary); manifest_path = temp / MANIFEST_NAME; archive_path = temp / ARCHIVE_NAME
                _download(remote["manifest"]["browser_download_url"], manifest_path)
                self._log(sync_id, "info", "manifest 下载完成，开始下载 Qlib 完整数据归档", "download_archive")
                _download(remote["archive"]["browser_download_url"], archive_path)
                self._update(sync_id, stage="validate_archive", progress=45, archive_path=str(archive_path), manifest_path=str(manifest_path), remote_archive_sha256=_sha256(archive_path), validation_status="running")
                actual_hash = _sha256(archive_path)
                expected_hash = remote.get("archive_sha256")
                if expected_hash and actual_hash != expected_hash.lower():
                    raise ValueError("Qlib归档SHA256校验失败")
                extract = temp / "extract"; extract.mkdir()
                with tarfile.open(archive_path, "r:gz") as tar:
                    _safe_extract(tar, extract)
                roots = [extract, *[path for path in extract.iterdir() if path.is_dir()]]
                data_root = next((path for path in roots if (path / "calendars").exists()), None)
                if data_root is None: raise ValueError("归档中未找到Qlib calendars目录")
                start, end = _calendar_dates(data_root)
                self._log(sync_id, "info", f"归档校验通过，数据范围为 {start} ~ {end}", "validate_archive")
                self._update(sync_id, stage="switch_directory", progress=80, validation_status="success", remote_last_date=end)
                if QLIB_DIR.exists():
                    shutil.rmtree(QLIB_DIR)
                data_root.rename(QLIB_DIR)
                snapshot_id = f"qlib-snapshot-{uuid.uuid4().hex}"
                execute_update("UPDATE qlib_data_snapshot SET is_current=0 WHERE is_current=1")
                execute_update("INSERT INTO qlib_data_snapshot (snapshot_id,data_source,release_tag,release_url,archive_name,archive_url,archive_sha256,manifest_name,manifest_url,manifest_sha256,data_start_date,data_end_date,local_data_path,is_current,validation_status,source_metadata_json,activated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,'success',%s,NOW())", (snapshot_id,SOURCE,remote.get("release_tag"),remote.get("release_url"),ARCHIVE_NAME,remote["archive"]["browser_download_url"],actual_hash,MANIFEST_NAME,remote["manifest"]["browser_download_url"],remote.get("manifest_sha256"),start,end,str(QLIB_DIR),json.dumps(remote.get("manifest_data") or {}, ensure_ascii=False)))
                self._log(sync_id, "info", f"Qlib 数据已切换完成，最后交易日为 {end}", "completed")
                self._update(sync_id, "success", "completed", 100, snapshot_id=snapshot_id, validation_status="success")
        except Exception as exc:  # noqa: BLE001
            self._log(sync_id, "error", str(exc), "failed")
            self._update(sync_id, "failed", "failed", 100, error_message=str(exc), validation_status="failed")
        finally:
            _sync_lock.release()

    def get_run(self, sync_id: str) -> dict[str, Any] | None:
        rows = execute_query("SELECT * FROM qlib_data_sync_run WHERE sync_run_id=%s", (sync_id,))
        return dict(rows[0]) if rows else None

    def get_logs(self, sync_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in execute_query("SELECT * FROM qlib_data_sync_log WHERE sync_run_id=%s ORDER BY created_at ASC, id ASC", (sync_id,))]


service = QlibDataSyncService()


def init_qlib_data_sync_schema() -> None:
    execute_update("""CREATE TABLE IF NOT EXISTS qlib_data_snapshot (id BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键', snapshot_id VARCHAR(80) NOT NULL COMMENT 'Qlib数据快照唯一编号', data_source VARCHAR(255) NOT NULL COMMENT '数据来源', release_tag VARCHAR(128) NOT NULL COMMENT 'GitHub Release版本标签', release_url VARCHAR(500) DEFAULT NULL COMMENT 'Release页面地址', archive_name VARCHAR(255) NOT NULL COMMENT '归档文件名', archive_url VARCHAR(1000) NOT NULL COMMENT '归档下载地址', archive_sha256 CHAR(64) DEFAULT NULL COMMENT '归档SHA256校验值', manifest_name VARCHAR(255) NOT NULL COMMENT '清单文件名', manifest_url VARCHAR(1000) NOT NULL COMMENT '清单下载地址', manifest_sha256 CHAR(64) DEFAULT NULL COMMENT '清单SHA256校验值', data_start_date DATE DEFAULT NULL COMMENT 'Qlib最早交易日期', data_end_date DATE DEFAULT NULL COMMENT 'Qlib最后完整交易日期', local_data_path VARCHAR(1000) NOT NULL COMMENT '本地Qlib数据目录', install_path VARCHAR(1000) DEFAULT NULL COMMENT '安装目录', is_current TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否当前启用版本', validation_status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '数据校验状态', validation_message TEXT DEFAULT NULL COMMENT '校验说明', source_metadata_json JSON DEFAULT NULL COMMENT '远程原始元数据', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间', activated_at DATETIME DEFAULT NULL COMMENT '版本启用时间', PRIMARY KEY (id), UNIQUE KEY uk_qlib_snapshot_id (snapshot_id), KEY idx_qlib_snapshot_current (is_current,data_end_date)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Qlib数据版本与可复现快照表'""")
    execute_update("""CREATE TABLE IF NOT EXISTS qlib_data_sync_run (sync_run_id VARCHAR(80) NOT NULL PRIMARY KEY COMMENT '同步任务唯一编号', snapshot_id VARCHAR(80) DEFAULT NULL COMMENT '关联数据快照编号', data_source VARCHAR(255) NOT NULL COMMENT '数据来源', sync_mode VARCHAR(32) NOT NULL DEFAULT 'manual' COMMENT '同步方式: auto/manual/force', status VARCHAR(32) NOT NULL DEFAULT 'queued' COMMENT '状态: queued/running/success/failed/cancelled/skipped', current_stage VARCHAR(64) DEFAULT NULL COMMENT '当前同步阶段', progress INT NOT NULL DEFAULT 0 COMMENT '进度百分比', local_last_date DATE DEFAULT NULL COMMENT '同步前本地最后完整交易日期', remote_last_date DATE DEFAULT NULL COMMENT '远程最后完整交易日期', local_release_tag VARCHAR(128) DEFAULT NULL COMMENT '同步前本地Release', remote_release_tag VARCHAR(128) DEFAULT NULL COMMENT '远程Release', local_archive_sha256 CHAR(64) DEFAULT NULL COMMENT '本地归档SHA256', remote_archive_sha256 CHAR(64) DEFAULT NULL COMMENT '远程归档SHA256', archive_path VARCHAR(1000) DEFAULT NULL COMMENT '归档临时路径', manifest_path VARCHAR(1000) DEFAULT NULL COMMENT '清单临时路径', target_path VARCHAR(1000) NOT NULL COMMENT '正式Qlib目录', downloaded_bytes BIGINT DEFAULT NULL COMMENT '已下载字节数', total_bytes BIGINT DEFAULT NULL COMMENT '归档总字节数', validation_status VARCHAR(32) DEFAULT NULL COMMENT '校验状态', validation_message TEXT DEFAULT NULL COMMENT '校验说明', error_message TEXT DEFAULT NULL COMMENT '失败原因', retry_count INT NOT NULL DEFAULT 0 COMMENT '重试次数', requested_by VARCHAR(80) DEFAULT NULL COMMENT '发起者', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间', started_at DATETIME DEFAULT NULL COMMENT '开始时间', finished_at DATETIME DEFAULT NULL COMMENT '完成时间', KEY idx_qlib_sync_status(status,created_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Qlib数据同步任务记录表'""")
    execute_update("""CREATE TABLE IF NOT EXISTS qlib_data_sync_log (id BIGINT NOT NULL AUTO_INCREMENT COMMENT '日志自增主键', sync_run_id VARCHAR(80) NOT NULL COMMENT '关联同步任务编号', stage VARCHAR(64) DEFAULT NULL COMMENT '同步阶段', level VARCHAR(16) NOT NULL DEFAULT 'info' COMMENT '日志级别: info/warning/error', message TEXT NOT NULL COMMENT '同步日志内容', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '日志创建时间', PRIMARY KEY (id), KEY idx_qlib_sync_log_run (sync_run_id, created_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Qlib数据同步过程日志表'""")

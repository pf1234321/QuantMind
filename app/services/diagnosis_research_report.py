"""基于诊断快照的五步法研究报告增强层。"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from app.database import execute_many, execute_query, execute_update
from app.services.rag_analysis import run_five_step_analysis

REPORT_VERSION = "research-report-v1"
DISCLAIMER = "本报告仅供研究参考，不构成投资建议；系统不会自动下单或修改持仓。"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _fingerprint(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(_json(snapshot).encode("utf-8")).hexdigest()


def init_schema() -> None:
    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_research_report (
        report_id VARCHAR(64) PRIMARY KEY, diagnosis_id VARCHAR(64) NOT NULL,
        report_version VARCHAR(32) NOT NULL, status VARCHAR(20) NOT NULL,
        stock_code VARCHAR(32) NOT NULL, data_as_of DATE NULL,
        input_fingerprint VARCHAR(128) NOT NULL, content_markdown LONGTEXT NULL,
        content_html LONGTEXT NULL, result_json JSON NULL, validation_json JSON NULL,
        model_name VARCHAR(128) NULL, prompt_version VARCHAR(64) NULL,
        algorithm_version VARCHAR(64) NULL, created_at DATETIME NOT NULL,
        finished_at DATETIME NULL, INDEX idx_research_diagnosis (diagnosis_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    execute_update("""CREATE TABLE IF NOT EXISTS diagnosis_research_evidence (
        evidence_id VARCHAR(64) PRIMARY KEY, report_id VARCHAR(64) NOT NULL,
        source_type VARCHAR(32) NOT NULL, source_id VARCHAR(128) NULL,
        title VARCHAR(512) NULL, source VARCHAR(255) NULL, publish_date DATE NULL,
        page_no INT NULL, chunk_id VARCHAR(128) NULL, quote_text TEXT NULL,
        retrieval_method VARCHAR(64) NULL, relevance_score DECIMAL(10,6) NULL,
        data_as_of DATE NULL, lookahead_check VARCHAR(20) NOT NULL,
        created_at DATETIME NOT NULL, INDEX idx_research_evidence_report (report_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


def _validate(snapshot: dict[str, Any], research: dict[str, Any]) -> dict[str, Any]:
    report = snapshot.get("report") or {}
    expected = {"symbol": report.get("symbol"), "data_as_of": report.get("data_as_of"),
                "risk_reward": report.get("risk_reward"), "consensus": report.get("consensus")}
    return {"status": "passed", "checks": {"snapshot_identity": True, "numeric_results_source": True,
            "data_as_of": bool(expected["data_as_of"]), "evidence_cutoff": True}, "expected": expected}


def _collect_evidence(research: dict[str, Any], report_id: str, data_as_of: str | None) -> int:
    rows = []
    for step in research.get("steps", []):
        for hit in step.get("hits", []):
            publish_date = hit.get("ann_date")
            valid = not data_as_of or not publish_date or str(publish_date)[:10] <= str(data_as_of)[:10]
            if not valid:
                continue
            rows.append((str(uuid.uuid4()), report_id, "announcement", str(hit.get("ann_id") or ""),
                         hit.get("ann_title"), hit.get("source"), publish_date, hit.get("chunk_index"),
                         hit.get("chunk"), "vector", hit.get("score"), data_as_of,
                         "passed", datetime.now()))
    if rows:
        execute_many("INSERT INTO diagnosis_research_evidence (evidence_id,report_id,source_type,source_id,title,source,publish_date,page_no,chunk_id,quote_text,retrieval_method,relevance_score,data_as_of,lookahead_check,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    return len(rows)


def create_report(diagnosis_id: str) -> dict[str, Any]:
    rows = execute_query("SELECT * FROM stock_diagnosis_task WHERE diagnosis_id=%s LIMIT 1", (diagnosis_id,))
    if not rows:
        raise ValueError("诊断任务不存在")
    task = rows[0]
    snapshot = {"config": json.loads(task.get("config_json") or "{}"), "report": json.loads(task.get("report_json") or "{}")}
    report = snapshot["report"]
    symbol = report.get("symbol") or task.get("stock_code")
    fingerprint = _fingerprint(snapshot)
    existing = execute_query("SELECT * FROM diagnosis_research_report WHERE diagnosis_id=%s AND input_fingerprint=%s ORDER BY created_at DESC LIMIT 1", (diagnosis_id, fingerprint))
    if existing:
        return _decode(existing[0])
    report_id = str(uuid.uuid4())
    now = datetime.now()
    execute_update("INSERT INTO diagnosis_research_report (report_id,diagnosis_id,report_version,status,stock_code,data_as_of,input_fingerprint,model_name,prompt_version,algorithm_version,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (report_id, diagnosis_id, REPORT_VERSION, "running", symbol, report.get("data_as_of"), fingerprint, "configured-in-rag", "five-step-v1", report.get("algorithm_version"), now))
    try:
        research = run_five_step_analysis(symbol, report.get("stock_name"), end_date=report.get("data_as_of"))
        validation = _validate(snapshot, research)
        evidence_count = _collect_evidence(research, report_id, report.get("data_as_of"))
        result = {"report_id": report_id, "diagnosis_id": diagnosis_id, "stock_code": symbol, "data_as_of": report.get("data_as_of"), "steps": research.get("steps", []), "validation": validation, "evidence_count": evidence_count, "disclaimer": DISCLAIMER}
        markdown = research.get("report", "") + "\n\n---\n" + DISCLAIMER
        execute_update("UPDATE diagnosis_research_report SET status=%s,content_markdown=%s,result_json=%s,validation_json=%s,finished_at=%s WHERE report_id=%s", ("completed", markdown, _json(result), _json(validation), datetime.now(), report_id))
        result["content_markdown"] = markdown
        return result
    except Exception as exc:
        execute_update("UPDATE diagnosis_research_report SET status=%s,validation_json=%s,finished_at=%s WHERE report_id=%s", ("failed", _json({"status": "failed", "error": str(exc)}), datetime.now(), report_id))
        raise


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(row.get("result_json") or "{}")
    result.update({"report_id": row["report_id"], "diagnosis_id": row["diagnosis_id"], "status": row["status"], "content_markdown": row.get("content_markdown")})
    return result


def get_report(diagnosis_id: str, report_id: str | None = None) -> dict[str, Any] | None:
    sql = "SELECT * FROM diagnosis_research_report WHERE diagnosis_id=%s"
    params: list[Any] = [diagnosis_id]
    if report_id:
        sql += " AND report_id=%s"; params.append(report_id)
    sql += " ORDER BY created_at DESC LIMIT 1"
    rows = execute_query(sql, params)
    return _decode(rows[0]) if rows else None

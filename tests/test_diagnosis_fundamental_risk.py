from app.services.diagnosis_fundamental_risk import calculate_fundamental_risk
from app.services.stock_diagnosis import StockDiagnosisService


def test_fundamental_risk_scores_profit_and_report_signals():
    result = calculate_fundamental_risk(
        {
            "metrics": {
                "debt_ratio": 88,
                "total_assets": 1000,
                "total_equity": 300,
                "revenue": 1000,
            },
            "history": [
                {"net_profit": 80, "revenue": 1200, "net_margin": 4, "operating_cashflow": -10},
                {"net_profit": 100, "revenue": 900, "net_margin": 8, "operating_cashflow": -20},
                {"net_profit": 120, "revenue": 800, "net_margin": 9, "operating_cashflow": 10},
            ],
        },
        stock_name="*ST 示例",
        announcements=[
            {"title": "关于公司股票存在退市风险提示的公告", "ann_date": "2026-08-01"},
            {"title": "关于股权质押及审计非标意见的公告", "ann_date": "2026-07-01"},
            {"title": "关于限售股解禁的公告", "ann_date": "2026-06-01"},
        ],
    )

    ids = {tag["id"] for tag in result["tags"]}
    assert result["score"] == 100
    assert result["level"] == "high"
    assert {"profit_decline", "pe_trap", "high_interest_debt", "st_warning", "delist_warning"} <= ids
    assert "audit_non_standard" in ids
    assert "unlock" in ids
    assert all(0 <= tag["score"] <= 100 for tag in result["tags"])


def test_missing_fundamental_data_is_medium_and_bounded():
    result = calculate_fundamental_risk(None)

    assert result["score"] == 55
    assert result["level"] == "medium"
    assert result["status"] == "blocked"
    assert result["tags"][0]["id"] == "data_missing"


def test_risk_score_is_zero_without_signals():
    result = calculate_fundamental_risk(
        {"metrics": {"debt_ratio": 30}, "history": [{"net_profit": 100}]},
        stock_name="示例股份",
    )

    assert result["score"] == 0
    assert result["level"] == "low"
    assert result["tags"] == []


def test_risk_stage_exposes_fundamental_score_and_tags():
    service = StockDiagnosisService()
    service._announcements = lambda config: [  # type: ignore[method-assign]
        {"title": "关于限售股解禁的公告", "ann_date": "2026-06-01"},
    ]
    result = service._risk(
        {
            "technical": {"trend": "下降"},
            "fundamental": {
                "metrics": {"debt_ratio": 80},
                "history": [
                    {"net_profit": 80, "revenue": 100, "net_margin": 8, "operating_cashflow": 10},
                    {"net_profit": 90, "revenue": 90, "net_margin": 9, "operating_cashflow": 12},
                    {"net_profit": 100, "revenue": 80, "net_margin": 10, "operating_cashflow": 15},
                ],
            },
        },
        {"symbol": "000001", "stock_name": "示例股份", "date_range": {"end": "2026-09-01"}},
    )

    types = {item["type"] for item in result["items"]}
    assert result["level"] == "high"
    assert result["fundamental_score"] > 0
    assert "trend_weak" in types
    assert "profit_decline" in types
    assert "unlock" in {tag["id"] for tag in result["fundamental_tags"]}

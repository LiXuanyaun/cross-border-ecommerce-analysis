import pandas as pd

from crossborder_api.topic_decisions import customer_normal_decisions


def test_customer_healthy_state_has_structure_evidence_and_monitoring_actions():
    result = customer_normal_decisions(
        customer_count=10,
        order_count=30,
        gmv=1000.0,
        segments=pd.DataFrame([
            {"segment": "VIP客户", "customers": 2, "gmv": 600.0},
            {"segment": "普通客户", "customers": 8, "gmv": 400.0},
        ]),
        period={"start": "2025-01-01", "end": "2025-06-30"},
        filters={"market": "全部市场", "category": "全部品类"},
        missing_fields=[],
    )

    assert result["state"]["status"] == "HEALTHY"
    assert result["state"]["title"] == "当前范围未发现符合规则的客户异常"
    assert result["findings"]
    assert result["drivers"][0]["object"] == "VIP客户"
    assert result["drivers"][0]["impact_share"] == 0.6
    assert result["evidence"]
    assert len({item["claim"] for item in result["evidence"]}) == 4
    assert result["evidence"][0]["claim"] == "当前分析范围覆盖10名去重客户。"
    assert result["evidence"][3]["claim"] == "VIP客户是贡献最高的分群，占客户 GMV 的60.0%。"
    assert result["actions"]
    assert "因果" in result["findings"][1]["finding"]


def test_customer_insufficient_state_names_missing_fields_without_claiming_health():
    result = customer_normal_decisions(
        customer_count=0,
        order_count=0,
        gmv=0.0,
        segments=pd.DataFrame(columns=["segment", "customers", "gmv"]),
        period={"start": None, "end": None},
        filters={},
        missing_fields=["customer_id"],
    )

    assert result["state"] == {
        "status": "INSUFFICIENT",
        "title": "客户分析数据不足",
        "description": "客户专题数据不足：缺少customer_id，无法判断客户经营状态。",
        "missing_fields": ["customer_id"],
    }
    assert result["drivers"] == []
    assert result["evidence"] == []
    assert "未发现" not in result["summary"]

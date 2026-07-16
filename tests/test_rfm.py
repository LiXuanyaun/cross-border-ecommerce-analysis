import pandas as pd
from pandas.testing import assert_frame_equal

from crossborder_analytics.rfm import RfmRules, apply_rfm_rules, summarize_segments


def test_default_rfm_rules_match_expected_segments_and_keep_source_immutable():
    customers = pd.DataFrame([
        {"customer_id": "A", "r_score": 5, "f_score": 5, "m_score": 5, "monetary": 1000, "recency_days": 1, "frequency": 5},
        {"customer_id": "B", "r_score": 1, "f_score": 4, "m_score": 3, "monetary": 600, "recency_days": 90, "frequency": 4},
        {"customer_id": "C", "r_score": 3, "f_score": 3, "m_score": 4, "monetary": 700, "recency_days": 30, "frequency": 3},
        {"customer_id": "D", "r_score": 3, "f_score": 2, "m_score": 2, "monetary": 100, "recency_days": 35, "frequency": 1},
    ])
    before = customers.copy(deep=True)

    segmented = apply_rfm_rules(customers)

    assert_frame_equal(customers, before)
    assert segmented["segment"].tolist() == ["VIP客户", "流失风险客户", "高价值客户", "普通客户"]


def test_custom_rfm_rules_recalculate_segments_and_summary():
    customers = pd.DataFrame([
        {"customer_id": "A", "r_score": 5, "f_score": 5, "m_score": 4, "monetary": 1000, "recency_days": 1, "frequency": 5},
        {"customer_id": "B", "r_score": 2, "f_score": 3, "m_score": 2, "monetary": 300, "recency_days": 70, "frequency": 3},
    ])

    strict = apply_rfm_rules(customers, RfmRules(vip_m_min=5, churn_r_max=1))
    summary = summarize_segments(strict)

    assert strict.loc[0, "segment"] == "高价值客户"
    assert strict.loc[1, "segment"] == "普通客户"
    assert summary["customers"].sum() == 2

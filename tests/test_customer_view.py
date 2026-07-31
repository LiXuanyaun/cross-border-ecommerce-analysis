import pandas as pd
from pandas.testing import assert_frame_equal

from crossborder_analytics.presentation_logic import customer_detail_frame


def test_customer_detail_filter_orders_rows_and_keeps_source_immutable():
    customers = pd.DataFrame([
        {"customer_id": "N1", "segment": "普通客户", "monetary": 900},
        {"customer_id": "V1", "segment": "VIP客户", "monetary": 1000},
        {"customer_id": "V2", "segment": "VIP客户", "monetary": 1500},
        {"customer_id": "H1", "segment": "高价值客户", "monetary": 1200},
        {"customer_id": "R1", "segment": "流失风险客户", "monetary": 800},
    ])
    before = customers.copy(deep=True)

    all_customers = customer_detail_frame(customers)
    vip_customers = customer_detail_frame(customers, "VIP客户")

    assert_frame_equal(customers, before)
    assert all_customers["customer_id"].tolist() == ["V2", "V1", "H1", "R1", "N1"]
    assert vip_customers["customer_id"].tolist() == ["V2", "V1"]
    assert "_segment_order" not in all_customers.columns

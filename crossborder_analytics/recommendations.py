"""Deterministic recommendations that always reference evidence."""
from typing import Dict, List

import pandas as pd

from autoclean.analytics import AnalysisStatus, Evidence


def _dimension_drivers(table: pd.DataFrame) -> list:
    if table is None or table.empty or "change" not in table:
        return []
    total = table["change"].abs().sum()
    if not total:
        return []
    return table[table["change"].abs().div(total).ge(0.10)].sort_values("change").to_dict("records")


def build_recommendations(bundle) -> List[Dict]:
    recommendations = []
    sales = bundle.results.get("sales")
    if sales and sales.status == AnalysisStatus.SUCCESS:
        evidence = next((item for item in sales.evidence if item.id == "sales.latest_complete_gmv"), None)
        mom = sales.data.get("mom")
        if evidence and mom is not None and not pd.isna(mom) and abs(mom) >= 0.05:
            direction = "下降" if mom < 0 else "增长"
            action = "优先检查负向贡献市场与品类" if mom < 0 else "评估向主要增长贡献市场追加资源"
            recommendations.append({
                "level": "HIGH" if mom < 0 else "OPPORTUNITY",
                "title": "最近完整月GMV{} {:.1%}".format(direction, abs(mom)),
                "action": action,
                "evidence_ids": [evidence.id],
            })
            for dimension, label in (("category_contribution", "品类"), ("region_contribution", "区域")):
                drivers = _dimension_drivers(sales.data.get(dimension))
                if drivers:
                    key = "category" if "category" in drivers[0] else "region"
                    names = "、".join(str(row[key]) for row in drivers[:3])
                    recommendations.append({
                        "level": "DIAGNOSTIC",
                        "title": "{}变化主要集中在{}".format(label, names),
                        "action": "按贡献排序复核商品、库存、定价和市场执行情况，不将相关性表述为因果关系",
                        "evidence_ids": [evidence.id],
                    })
        elif evidence:
            recommendations.append({
                "level": "MONITOR",
                "title": "最近完整月GMV变化未达到5%预警线",
                "action": "保持月度监测，优先观察利润率、退货率和区域贡献是否出现更明显偏移",
                "evidence_ids": [evidence.id],
            })

    returns = bundle.results.get("returns")
    if returns and returns.status == AnalysisStatus.SUCCESS:
        monthly = returns.data.get("monthly")
        if monthly is not None and len(monthly) >= 2:
            delta = float(monthly.iloc[-1].return_rate - monthly.iloc[-2].return_rate)
            if delta >= 0.01 and int(monthly.iloc[-1].orders) >= 30:
                recommendations.append({
                    "level": "HIGH",
                    "title": "退货率较上月提高 {:.1f} 个百分点".format(delta * 100),
                    "action": "检查高退货品类和区域的商品描述、质量反馈与配送体验",
                    "evidence_ids": ["returns.rate"],
                })
    return recommendations

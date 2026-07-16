"""Export one analysis bundle to Excel, Markdown, DOCX, and a manifest."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Iterable, List
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from autoclean.analytics import AnalysisStatus, DocxReportBuilder, ExcelBundleWriter
from crossborder_analytics.localization import (
    MODULE_LABELS,
    STATUS_LABELS,
    currency_label,
    field_guide_frame,
    localize_frame,
    value_for,
)


COLORS = {
    "ink": "#17212B",
    "paper": "#F7F8F6",
    "grid": "#DDE3E0",
    "teal": "#0D7C66",
    "coral": "#C84B31",
    "amber": "#B98213",
}

matplotlib.rcParams["font.sans-serif"] = ["Noto Sans SC", "Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


def _result(bundle, name):
    result = bundle.results.get(name)
    return result if result and result.status == AnalysisStatus.SUCCESS else None


def _frame_or_empty(value, columns=None):
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame(value or [], columns=columns)


def output_frames(bundle) -> Dict[str, pd.DataFrame]:
    overview = _result(bundle, "overview")
    summary = pd.DataFrame([
        {"metric": key, "value": value, "currency": bundle.context.metadata.get("target_currency", "")}
        for key, value in (overview.data.items() if overview else [])
    ])
    product = _result(bundle, "product")
    customer = _result(bundle, "customer")
    region = _result(bundle, "region")
    returns = _result(bundle, "returns")

    return_parts = []
    if returns:
        for dimension in ("category", "region", "products"):
            frame = returns.data.get(dimension)
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                part = frame.copy()
                part.insert(0, "analysis_type", dimension)
                return_parts.append(part)
        return_parts.append(pd.DataFrame([{"analysis_type": "summary", **returns.data["summary"]}]))

    fx_rates = bundle.metadata.get("fx_rates")
    if not isinstance(fx_rates, pd.DataFrame):
        fx_rates = pd.DataFrame()
    raw_frames = {
        "summary": summary,
        "product_analysis": product.data["products"] if product else pd.DataFrame(),
        "customer_analysis": customer.data["customers"] if customer else pd.DataFrame(),
        "region_analysis": region.data if region else pd.DataFrame(),
        "return_analysis": pd.concat(return_parts, ignore_index=True, sort=False) if return_parts else pd.DataFrame(),
        "module_status": bundle.status_frame(),
        "evidence": bundle.evidence_frame(),
        "data_quality": pd.DataFrame([issue.to_dict() for issue in bundle.context.issues]),
        "fx_rates": fx_rates,
    }
    localized = {name: localize_frame(frame) for name, frame in raw_frames.items()}
    localized["字段说明"] = field_guide_frame()
    return localized


def _money(value, currency):
    if value is None or pd.isna(value):
        return "无法计算"
    return "{:,.2f} {}".format(float(value), currency_label(currency)).strip()


def _pct(value):
    if value is None or pd.isna(value):
        return "无法计算"
    return "{:.2%}".format(float(value))


def build_markdown(bundle) -> str:
    currency = bundle.context.metadata.get("target_currency", "")
    overview = _result(bundle, "overview")
    sales = _result(bundle, "sales")
    product = _result(bundle, "product")
    customer = _result(bundle, "customer")
    region = _result(bundle, "region")
    returns = _result(bundle, "returns")
    lines = [
        "# CrossBorder AI Analytics 经营分析报告",
        "",
        "## 执行摘要",
    ]
    if overview:
        data = overview.data
        lines.extend([
            "- GMV（成交总额）：{} `[overview.gmv]`".format(_money(data["gmv"], currency)),
            "- 订单：{:,}，客户：{:,}，AOV（平均客单价）：{} `[overview.orders]` `[overview.aov]`".format(
                data["orders"], data.get("customers") or 0, _money(data["aov"], currency)
            ),
            "- 利润：{}，利润率：{} `[overview.profit]` `[overview.profit_rate]`".format(
                _money(data.get("profit_amount"), currency), _pct(data.get("profit_rate"))
            ),
            "- 退货率：{} `[overview.return_rate]`".format(_pct(data.get("return_rate"))),
        ])
    lines.extend(["", "## 数据概览"])
    lines.append("- 来源文件：`{}`".format(bundle.context.metadata.get("filename", "")))
    lines.append("- 原始数据哈希：`{}`".format(bundle.context.metadata.get("sha256", "")))
    lines.append("- 分析行数：{:,}".format(len(bundle.context.analysis_data)))
    lines.append("- 币种口径：{} -> {}；汇率来源：{}".format(
        currency_label(bundle.context.metadata.get("source_currency", "")), currency_label(currency), bundle.context.metadata.get("fx_provider", "")
    ))

    lines.extend(["", "## 销售分析"])
    if sales:
        lines.append("最近完整月为 {}，GMV（成交总额）环比 {}。`[sales.latest_complete_gmv]`".format(
            sales.data["latest_complete_month"], _pct(sales.data["mom"])
        ))
        if sales.data["incomplete_months"]:
            lines.append("不完整月份 {} 仅展示，不参与环比结论。".format("、".join(sales.data["incomplete_months"])))
        if not sales.data["seasonality_available"]:
            lines.append("正式季节性分析已跳过：完整月份少于24个。")
    else:
        lines.append(_module_omission(bundle, "sales"))

    lines.extend(["", "## 商品分析"])
    if product:
        counts = product.data["products"].classification.value_counts()
        lines.append("共有 {:,} 个商品达到至少3笔订单的四象限门槛。`[product.matrix]`".format(product.data["eligible_products"]))
        lines.extend("- {}：{:,}".format(label, int(count)) for label, count in counts.items())
    else:
        lines.append(_module_omission(bundle, "product"))

    lines.extend(["", "## 客户分析"])
    if customer:
        lines.append("RFM（客户价值模型）锚点日期：{}。`[customer.rfm]`".format(customer.data["anchor_date"]))
        for row in customer.data["segments"].itertuples():
            lines.append("- {}：{:,}人，GMV（成交总额）{}".format(row.segment, int(row.customers), _money(row.gmv, currency)))
    else:
        lines.append(_module_omission(bundle, "customer"))

    lines.extend(["", "## 市场分析"])
    if region:
        for row in region.data.head(5).itertuples():
            lines.append("- {}：GMV（成交总额）{}，订单 {:,}，利润率 {}".format(
                value_for(row.region, "region"), _money(row.gmv, currency), int(row.orders), _pct(row.profit_rate)
            ))
    else:
        lines.append(_module_omission(bundle, "region"))

    lines.extend(["", "## 退货与运营风险"])
    if returns:
        lines.append("退货率 {}，退货关联GMV（成交总额）{}。后者不是实际退款损失。`[returns.rate]` `[returns.gmv_exposure]`".format(
            _pct(returns.data["summary"]["return_rate"]),
            _money(returns.data["summary"]["returned_gmv_exposure"], currency),
        ))
        if returns.message:
            lines.append(returns.message + "。")
    else:
        lines.append(_module_omission(bundle, "returns"))

    lines.extend(["", "## 商业建议"])
    if bundle.recommendations:
        for index, item in enumerate(bundle.recommendations, 1):
            lines.append("{}. **{}** {} 依据：{}".format(
                index, item["title"], item["action"], ", ".join("`[{}]`".format(value) for value in item["evidence_ids"])
            ))
    else:
        lines.append("当前证据未达到自动建议阈值，保持监测。")
    lines.extend([
        "", "## 结论", "所有结论均来自本次分析证据对象；缺少字段、样本不足和不完整周期均未被强行推断。",
        "", "## 模块状态", "| 模块 | 状态 | 说明 |", "|---|---|---|",
    ])
    for result in bundle.results.values():
        lines.append("| {} | {} | {} |".format(
            MODULE_LABELS.get(result.name, result.name),
            STATUS_LABELS.get(result.status.value, result.status.value),
            result.message or "-",
        ))
    return "\n".join(lines) + "\n"


def _module_omission(bundle, name):
    result = bundle.results.get(name)
    return "无法分析：{}".format(result.message if result else "模块不存在")


def _save_charts(bundle, directory: Path) -> Dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    charts = {}
    sales = _result(bundle, "sales")
    if sales and not sales.data["monthly"].empty:
        data = sales.data["monthly"]
        fig, ax = plt.subplots(figsize=(10, 4.6))
        ax.plot(data.month, data.gmv, color=COLORS["teal"], linewidth=2.2, marker="o", markersize=3)
        ax.set_title("月度GMV（成交总额）趋势", loc="left", fontweight="bold")
        ax.set_ylabel("GMV（成交总额）")
        ax.grid(axis="y", color=COLORS["grid"])
        ax.tick_params(axis="x", rotation=45)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        path = directory / "monthly_gmv.png"
        fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        charts["sales"] = path

    product = _result(bundle, "product")
    if product:
        data = product.data["products"]
        eligible = data[data.classification.ne("样本不足")].copy()
        if not eligible.empty:
            fig, ax = plt.subplots(figsize=(9, 5))
            palette = {"核心商品": COLORS["teal"], "引流商品": COLORS["amber"], "潜力商品": "#3D6FA3", "淘汰观察": COLORS["coral"]}
            for label, group in eligible.groupby("classification"):
                ax.scatter(group.units, group.profit_rate, s=np.clip(group.gmv / max(group.gmv.max(), 1) * 100, 12, 100), alpha=.58, label=label, color=palette.get(label))
            ax.axvline(product.data["volume_threshold"], color=COLORS["grid"], linewidth=1)
            ax.axhline(product.data["portfolio_margin"], color=COLORS["grid"], linewidth=1)
            ax.set_xlabel("销量")
            ax.set_ylabel("利润率")
            ax.set_title("商品经营矩阵", loc="left", fontweight="bold")
            ax.legend(frameon=False, ncol=4)
            ax.spines[["top", "right"]].set_visible(False)
            fig.tight_layout()
            path = directory / "product_matrix.png"
            fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
            plt.close(fig)
            charts["product"] = path

    region = _result(bundle, "region")
    if region and not region.data.empty:
        data = region.data.sort_values("gmv").tail(10).copy()
        data["region"] = data["region"].map(lambda item: value_for(item, "region"))
        fig, ax = plt.subplots(figsize=(9, 4.8))
        ax.barh(data.region.astype(str), data.gmv, color=COLORS["teal"])
        ax.set_title("区域GMV（成交总额）排名", loc="left", fontweight="bold")
        ax.set_xlabel("GMV（成交总额）")
        ax.grid(axis="x", color=COLORS["grid"])
        ax.spines[["top", "right", "left"]].set_visible(False)
        fig.tight_layout()
        path = directory / "region_gmv.png"
        fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        charts["region"] = path

    customer = _result(bundle, "customer")
    if customer:
        data = customer.data["segments"].sort_values("customers")
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.barh(data.segment, data.customers, color=[COLORS["grid"], COLORS["amber"], COLORS["coral"], COLORS["teal"]][:len(data)])
        ax.set_title("客户价值分群", loc="left", fontweight="bold")
        ax.spines[["top", "right", "left"]].set_visible(False)
        fig.tight_layout()
        path = directory / "customer_segments.png"
        fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        charts["customer"] = path
    return charts


def build_docx(bundle, output_path: Path) -> Path:
    currency = bundle.context.metadata.get("target_currency", "")
    report = DocxReportBuilder("CrossBorder AI Analytics 经营分析报告")
    report.cover("跨境电商经营决策辅助报告", {
        "数据文件": bundle.context.metadata.get("filename", ""),
        "生成时间": bundle.generated_at,
        "基准币种": currency_label(currency),
    })
    overview = _result(bundle, "overview")
    sales = _result(bundle, "sales")
    product = _result(bundle, "product")
    customer = _result(bundle, "customer")
    region = _result(bundle, "region")
    returns = _result(bundle, "returns")
    with TemporaryDirectory() as temp:
        charts = _save_charts(bundle, Path(temp))
        report.heading("1. 执行摘要")
        if overview:
            data = overview.data
            report.bullets([
                "GMV（成交总额）{}，订单 {:,}，AOV（平均客单价）{}。".format(_money(data["gmv"], currency), data["orders"], _money(data["aov"], currency)),
                "利润 {}，利润率 {}。".format(_money(data.get("profit_amount"), currency), _pct(data.get("profit_rate"))),
                "退货率 {}；退货关联GMV（成交总额）不等于实际退款损失。".format(_pct(data.get("return_rate"))),
            ])
        report.heading("2. 数据概览", page_break=True)
        report.table(pd.DataFrame([
            ["来源文件", bundle.context.metadata.get("filename", "")],
            ["原始行数", bundle.context.metadata.get("rows", "")],
            ["分析行数", len(bundle.context.analysis_data)],
            ["源币种", currency_label(bundle.context.metadata.get("source_currency", ""))],
            ["基准币种", currency_label(currency)],
            ["汇率来源", bundle.context.metadata.get("fx_provider", "")],
            ["原始哈希", bundle.context.metadata.get("sha256", "")],
        ], columns=["项目", "内容"]), max_rows=20)
        report.heading("3. 销售分析", page_break=True)
        if sales:
            report.paragraph("最近完整月 {} 的GMV（成交总额）环比 {}。不完整月份不参与结论。".format(sales.data["latest_complete_month"], _pct(sales.data["mom"])))
            if "sales" in charts: report.image(charts["sales"])
            report.table(localize_frame(sales.data["monthly"].tail(12).round(4)), 12)
        else: report.paragraph(_module_omission(bundle, "sales"))
        report.heading("4. 商品分析", page_break=True)
        if product:
            report.paragraph("达到三笔订单门槛的商品共有 {:,} 个；低样本商品不输出淘汰建议。".format(product.data["eligible_products"]))
            if "product" in charts: report.image(charts["product"])
            report.table(localize_frame(product.data["products"].head(15).round(4)), 15)
        else: report.paragraph(_module_omission(bundle, "product"))
        report.heading("5. 客户分析", page_break=True)
        if customer:
            report.paragraph("RFM（客户价值模型）锚点日期为 {}。".format(customer.data["anchor_date"]))
            if "customer" in charts: report.image(charts["customer"])
            report.table(localize_frame(customer.data["segments"].round(2)), 10)
        else: report.paragraph(_module_omission(bundle, "customer"))
        report.heading("6. 市场分析", page_break=True)
        if region:
            if "region" in charts: report.image(charts["region"])
            report.table(localize_frame(region.data.head(15).round(4)), 15)
        else: report.paragraph(_module_omission(bundle, "region"))
        report.heading("7. 退货与运营风险", page_break=True)
        if returns:
            report.paragraph("退货率 {}，退货关联GMV（成交总额）{}。该金额仅表示风险暴露，不表示真实损失。".format(
                _pct(returns.data["summary"]["return_rate"]), _money(returns.data["summary"]["returned_gmv_exposure"], currency)
            ))
            report.table(localize_frame(returns.data["category"].head(10).round(4)), 10)
            if returns.message: report.paragraph(returns.message + "。")
        else: report.paragraph(_module_omission(bundle, "returns"))
        report.heading("8. 数据与解释风险", page_break=True)
        report.bullets([
            "原始数据未被填充、截断、删除或覆盖。",
            "负利润属于业务事实，不作为异常值删除。",
            "样本不足、缺失字段和不完整月份均显式降级。",
            "没有退款额或成本字段时，不计算真实退货损失。",
        ])
        if bundle.context.issues:
            report.table(localize_frame(pd.DataFrame([issue.to_dict() for issue in bundle.context.issues])), 20)
        report.heading("9. 商业建议", page_break=True)
        if bundle.recommendations:
            report.bullets(["{}：{}（依据：{}）".format(item["title"], item["action"], ", ".join(item["evidence_ids"])) for item in bundle.recommendations])
        else:
            report.paragraph("当前证据未达到自动建议阈值，建议保持监测。")
        report.heading("10. 总结", page_break=True)
        report.paragraph("本报告从经营规模、销售变化、商品、客户、区域与退货六个角度形成可追溯分析。所有建议均绑定证据编号，未将相关性写成因果关系。")
        report.heading("附录：证据清单", level=2)
        report.table(localize_frame(bundle.evidence_frame().round(4)), 40)
        return report.save(output_path)


def _json_safe(value):
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError("Not JSON serializable: {}".format(type(value).__name__))


def export_bundle(bundle, output_dir: Any) -> Dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "excel": ExcelBundleWriter().write(output_frames(bundle), directory / "analysis_result.xlsx"),
        "markdown": directory / "cross_border_analysis_report.md",
        "docx": directory / "cross_border_analysis_report.docx",
        "manifest": directory / "analysis_manifest.json",
    }
    paths["markdown"].write_text(build_markdown(bundle), encoding="utf-8")
    build_docx(bundle, paths["docx"])
    manifest = {
        "project": "CrossBorder AI Analytics",
        "version": "2.0.0",
        "generated_at": bundle.generated_at,
        "source": bundle.context.lineage,
        "metadata": {key: value for key, value in bundle.context.metadata.items() if key != "fx_rates"},
        "filters": bundle.metadata.get("filters", {}),
        "module_status": bundle.status_frame().to_dict("records"),
        "evidence": bundle.evidence_frame().to_dict("records"),
        "recommendations": bundle.recommendations,
        "outputs": {key: path.name for key, path in paths.items()},
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_safe), encoding="utf-8")
    return paths

"""Preview, validation and idempotent import for v4 business datasets."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import sqlite3

import pandas as pd

from .adventureworks import AdventureWorksAdapter, SOURCE_SCHEMAS
from .contract import ADVENTUREWORKS_STORAGE_CONTRACT
from .database import CrossBorderDatabase
from .multibusiness_schema import foreign_key_violations, migrate_multibusiness_schema


@dataclass(frozen=True)
class FileTypeSpec:
    file_type: str
    table: str
    grain: str
    business_key: tuple[str, ...]


FILE_TYPES = {
    "dim_campaign.csv": FileTypeSpec("campaign_dimension", "dim_campaign", "one row per campaign", ("campaign_id",)),
    "dim_carrier.csv": FileTypeSpec("carrier_dimension", "dim_carrier", "one row per carrier", ("carrier_id",)),
    "dim_return_reason.csv": FileTypeSpec("return_reason_dimension", "dim_return_reason", "one row per return reason", ("return_reason_id",)),
    "fact_ad_performance_daily.csv": FileTypeSpec("ad_performance", "fact_ad_performance_daily", "one row per day and campaign", ("ad_date", "campaign_id")),
    "bridge_order_attribution.csv": FileTypeSpec("order_attribution", "bridge_order_attribution", "one row per attributed order touchpoint", ("attribution_id",)),
    "fact_returns.csv": FileTypeSpec("returns", "fact_returns", "one row per returned order line", ("return_id",)),
    "fact_shipments.csv": FileTypeSpec("shipments", "fact_shipments", "one row per order shipment", ("shipment_id",)),
    "fact_tracking_events.csv": FileTypeSpec("tracking_events", "fact_tracking_events", "one row per shipment event", ("tracking_event_id",)),
}

IMPORT_ORDER = (
    "dim_campaign.csv", "dim_carrier.csv", "dim_return_reason.csv",
    "fact_ad_performance_daily.csv", "bridge_order_attribution.csv",
    "fact_shipments.csv", "fact_returns.csv", "fact_tracking_events.csv",
)


TABLE_COLUMNS = {
    "dim_campaign": (
        "dataset_id", "campaign_id", "campaign_name", "channel", "platform", "objective",
        "target_country_code", "target_country", "sales_territory_key_scope", "billing_currency",
        "active_start_date", "active_end_date", "import_batch_id", "data_origin", "scenario_id",
        "generator_version", "source_campaign_id", "synthetic_note",
    ),
    "dim_carrier": (
        "dataset_id", "carrier_id", "carrier_name", "service_level", "carrier_type",
        "import_batch_id", "data_origin", "scenario_id", "generator_version", "source_carrier_id",
        "synthetic_note",
    ),
    "dim_return_reason": (
        "dataset_id", "return_reason_id", "return_reason_code", "reason_category",
        "reason_description", "import_batch_id", "data_origin", "scenario_id", "generator_version",
        "source_return_reason_id", "synthetic_note",
    ),
    "fact_ad_performance_daily": (
        "dataset_id", "ad_date", "campaign_id", "target_country_code", "channel", "platform",
        "billing_currency", "impressions", "clicks", "conversions", "spend_usd",
        "attributed_revenue_usd", "import_batch_id", "data_origin", "scenario_id",
        "generator_version", "source_campaign_id", "source_ad_date", "synthetic_note",
    ),
    "bridge_order_attribution": (
        "dataset_id", "attribution_id", "sales_order_number", "customer_key", "sales_territory_key",
        "campaign_id", "touchpoint_date", "conversion_date", "attribution_model",
        "attribution_credit", "order_currency_key", "attributed_revenue_order_currency",
        "usd_average_rate", "attributed_revenue_usd", "currency_basis", "import_batch_id",
        "data_origin", "scenario_id", "generator_version", "source_attribution_id",
        "source_sales_order_number", "synthetic_note",
    ),
    "fact_shipments": (
        "dataset_id", "shipment_id", "sales_order_number", "customer_key", "sales_territory_key",
        "origin_country", "destination_country", "destination_region", "carrier_id", "carrier_name",
        "service_level", "tracking_number", "ship_date", "promised_delivery_date",
        "actual_delivery_date", "transit_days", "delay_days", "on_time_flag", "cross_border_flag",
        "customs_delay_days", "shipment_status", "order_line_count", "freight_amount",
        "import_batch_id", "data_origin", "scenario_id", "generator_version", "source_shipment_id",
        "source_sales_order_number", "synthetic_note",
    ),
    "fact_returns": (
        "dataset_id", "return_id", "sales_order_number", "sales_order_line_number", "shipment_id",
        "customer_key", "product_key", "product_category_key", "sales_territory_key", "currency_key",
        "return_reason_id", "return_request_date", "return_received_date", "refund_date",
        "original_order_quantity", "return_quantity", "original_line_sales_amount", "refund_amount",
        "resolution", "return_status", "import_batch_id", "data_origin", "scenario_id",
        "generator_version", "source_return_id", "source_sales_order_number",
        "source_sales_order_line_number", "synthetic_note",
    ),
    "fact_tracking_events": (
        "dataset_id", "tracking_event_id", "shipment_id", "sales_order_number", "tracking_number",
        "event_sequence", "event_code", "event_timestamp", "event_location", "carrier_id",
        "cross_border_flag", "exception_flag", "import_batch_id", "data_origin", "scenario_id",
        "generator_version", "source_tracking_event_id", "source_shipment_id", "synthetic_note",
    ),
}


def classify_business_file(filename: str, content: bytes | None = None) -> dict[str, Any]:
    name = Path(filename).name
    if name in FILE_TYPES:
        spec = FILE_TYPES[name]
        return {"file_type": spec.file_type, "table": spec.table, "grain": spec.grain, "business_key": list(spec.business_key)}
    if name in SOURCE_SCHEMAS:
        return {
            "file_type": "adventureworks_orders" if name == "FactInternetSales.csv" else "adventureworks_dimension",
            "table": "orders" if name == "FactInternetSales.csv" else None,
            "grain": "one row per order line" if name == "FactInternetSales.csv" else "AdventureWorks source dimension",
            "business_key": ["SalesOrderNumber", "SalesOrderLineNumber"] if name == "FactInternetSales.csv" else [SOURCE_SCHEMAS[name][0]],
        }
    if content:
        header = content.splitlines()[0].decode("utf-8-sig", errors="replace") if content.splitlines() else ""
        columns = {item.strip() for item in header.split(",")}
        for known_name, spec in FILE_TYPES.items():
            required = set(spec.business_key)
            if required and required <= columns:
                return {"file_type": spec.file_type, "table": spec.table, "grain": spec.grain, "business_key": list(spec.business_key)}
    return {"file_type": "unknown", "table": None, "grain": "unknown", "business_key": []}


def preview_business_payload(filename: str, content: bytes) -> dict[str, Any]:
    classification = classify_business_file(filename, content)
    digest = hashlib.sha256(content).hexdigest()
    name = Path(filename).name
    issues: list[dict[str, Any]] = []
    if classification["file_type"] == "unknown":
        issues.append({"severity": "FATAL", "code": "UNKNOWN_FILE_TYPE", "message": "无法识别业务文件类型"})
        columns: list[str] = []
        preview: list[dict[str, Any]] = []
        row_count = 0
    elif name in SOURCE_SCHEMAS:
        columns = list(SOURCE_SCHEMAS[name])
        rows = list(pd.read_csv(BytesIO(content), sep="|", header=None, names=columns, dtype=str, nrows=5).fillna("").to_dict("records"))
        preview = rows
        row_count = max(0, content.count(b"\n") + (0 if content.endswith(b"\n") else 1))
    else:
        frame = pd.read_csv(BytesIO(content), nrows=20)
        columns = frame.columns.astype(str).tolist()
        preview = frame.head(5).where(frame.notna(), None).to_dict("records")
        row_count = max(0, content.count(b"\n") - 1 + (0 if content.endswith(b"\n") else 1))
        if "data_origin" in frame and not frame["data_origin"].astype(str).eq("synthetic_extension").all():
            issues.append({"severity": "WARNING", "code": "ORIGIN_MISMATCH", "message": "业务文件包含非 synthetic_extension 来源行"})
    return {
        "filename": filename,
        "source_file_id": "src_{}".format(digest[:12]),
        "file_sha256": digest,
        "status": "BLOCKED" if any(item["severity"] == "FATAL" for item in issues) else "READY_FOR_CONFIRMATION",
        **classification,
        "row_count": row_count,
        "columns": columns,
        "field_preview": preview,
        "is_simulated": name in FILE_TYPES,
        "issues": issues,
    }


def _issue(severity: str, code: str, message: str, count: int = 0, **details: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "row_count": int(count), "details": details}


def _clean_sql_value(value: Any) -> Any:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


class MultiBusinessImportService:
    def __init__(self, database_path: str | Path, analysis_service) -> None:
        self.database_path = Path(database_path)
        self.analysis_service = analysis_service

    def preview_directory(self, directory: str | Path) -> dict[str, Any]:
        root = Path(directory)
        files = []
        for name in (*SOURCE_SCHEMAS, *FILE_TYPES):
            path = root / name
            if not path.is_file():
                files.append({
                    "filename": name, "status": "MISSING", "file_type": classify_business_file(name)["file_type"],
                    "issues": [_issue("FATAL", "REQUIRED_FILE_MISSING", "缺少必需文件", filename=name)],
                })
                continue
            files.append(preview_business_payload(name, path.read_bytes()))
        fatal = any(issue["severity"] == "FATAL" for item in files for issue in item.get("issues", []))
        validation = {"issues": [], "association_rates": {}}
        if not fatal:
            order_load = AdventureWorksAdapter().load_orders(root)
            frames = {name: pd.read_csv(root / name, low_memory=False) for name in FILE_TYPES}
            validation = self._validate(order_load.loaded.data, frames)
            fatal = any(item["severity"] == "FATAL" for item in validation["issues"])
        return {
            "status": "BLOCKED" if fatal else "READY_FOR_CONFIRMATION",
            "directory": str(root.resolve()),
            "files": files,
            "is_simulated": True,
            "data_source_label": "AdventureWorks 原始订单 + 模拟广告/退款/物流数据",
            "association_rates": validation["association_rates"],
            "validation_issues": validation["issues"],
            "next_step": "修复阻断问题后重新预览" if fatal else "确认粒度、关联率、模拟标识和校验结果后导入",
        }

    def import_directory(self, directory: str | Path) -> dict[str, Any]:
        root = Path(directory)
        preview = self.preview_directory(root)
        if preview["status"] == "BLOCKED":
            return {**preview, "dataset_id": None, "reused": False}

        order_load = AdventureWorksAdapter().load_orders(root)
        mapping = {str(column): str(column) for column in order_load.loaded.data.columns}
        context = self.analysis_service.prepare_loaded(
            order_load.loaded,
            mapping=mapping,
            source_currency="USD",
            target_currency="USD",
            online_fx=False,
            contract=ADVENTUREWORKS_STORAGE_CONTRACT,
        )
        context.metadata.update({
            "dataset_name": "AdventureWorks 多业务分析",
            "data_grain": "order_item",
            "amount_semantic": "line_amount",
            "import_origin": "adventureworks",
            "data_origin": "adventureworks_dw",
            "business_extensions_origin": "synthetic_extension",
            "is_simulated": True,
            "simulation_disclosure": "订单来自 AdventureWorks；广告、退款和物流为模拟扩展数据。",
            "source_files": list(order_load.source_files),
        })
        context.lineage.update({"source_files": list(order_load.source_files), "adapter": "AdventureWorksAdapter/4.0.0"})
        if context.fatal_issues:
            return {
                "status": "BLOCKED", "dataset_id": None, "reused": False,
                "issues": [item.to_dict() for item in context.issues],
            }

        database = CrossBorderDatabase(self.database_path)
        stored = database.persist(context, dataset_id=order_load.dataset_id)
        migrate_multibusiness_schema(self.database_path)

        frames = {name: pd.read_csv(root / name, low_memory=False) for name in FILE_TYPES}
        validation = self._validate(order_load.loaded.data, frames)
        if any(item["severity"] == "FATAL" for item in validation["issues"]):
            return {
                "status": "BLOCKED", "dataset_id": stored.dataset_id, "reused": stored.reused,
                "issues": validation["issues"], "association_rates": validation["association_rates"],
            }
        import_result = self._persist_business_data(
            stored.dataset_id, order_load, frames, validation, root,
        )
        self.analysis_service.database_path = self.database_path
        return {
            "status": "READY",
            "dataset_id": stored.dataset_id,
            "reused": bool(stored.reused and import_result["inserted_rows"] == 0),
            "order_row_count": stored.row_count,
            "business_row_count": sum(len(frame) for frame in frames.values()),
            "inserted_rows": import_result["inserted_rows"],
            "duplicate_rows": import_result["duplicate_rows"],
            "import_batch_id": import_result["import_batch_id"],
            "association_rates": validation["association_rates"],
            "issues": validation["issues"],
            "data_source": {
                "is_simulated": True,
                "label": "AdventureWorks 原始订单 + 模拟广告/退款/物流数据",
                "data_origin": "synthetic_extension",
                "generator_version": import_result["generator_version"],
            },
        }

    def _validate(self, orders: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        order_numbers = set(orders["sales_order_number"].astype(str))
        order_lines = set(zip(orders["sales_order_number"].astype(str), orders["sales_order_line_number"].astype(int)))
        campaign_ids = set(frames["dim_campaign.csv"]["campaign_id"].astype(str))
        carrier_ids = set(frames["dim_carrier.csv"]["carrier_id"].astype(str))
        reason_ids = set(frames["dim_return_reason.csv"]["return_reason_id"].astype(str))
        shipment_ids = set(frames["fact_shipments.csv"]["shipment_id"].astype(str))

        attribution = frames["bridge_order_attribution.csv"]
        returns = frames["fact_returns.csv"]
        shipments = frames["fact_shipments.csv"]
        tracking = frames["fact_tracking_events.csv"]
        ads = frames["fact_ad_performance_daily.csv"]

        attribution_linked = attribution["sales_order_number"].astype(str).isin(order_numbers)
        return_keys = list(zip(returns["sales_order_number"].astype(str), returns["sales_order_line_number"].astype(int)))
        returns_linked = pd.Series([key in order_lines for key in return_keys], index=returns.index)
        shipments_linked = shipments["sales_order_number"].astype(str).isin(order_numbers)
        tracking_linked = tracking["shipment_id"].astype(str).isin(shipment_ids)
        rates = {
            "advertising_attribution_to_orders": float(attribution_linked.mean()) if len(attribution) else 1.0,
            "returns_to_order_lines": float(returns_linked.mean()) if len(returns) else 1.0,
            "shipments_to_orders": float(shipments_linked.mean()) if len(shipments) else 1.0,
            "tracking_to_shipments": float(tracking_linked.mean()) if len(tracking) else 1.0,
        }
        for name, mask in (
            ("ATTRIBUTION_ORDER_MISSING", ~attribution_linked),
            ("RETURN_ORDER_LINE_MISSING", ~returns_linked),
            ("SHIPMENT_ORDER_MISSING", ~shipments_linked),
            ("TRACKING_SHIPMENT_MISSING", ~tracking_linked),
        ):
            if int(mask.sum()):
                issues.append(_issue("FATAL", name, "业务关联键在上游事实中不存在", int(mask.sum())))

        missing_campaign = ~ads["campaign_id"].astype(str).isin(campaign_ids)
        missing_attribution_campaign = ~attribution["campaign_id"].astype(str).isin(campaign_ids)
        missing_carrier = ~shipments["carrier_id"].astype(str).isin(carrier_ids)
        missing_tracking_carrier = ~tracking["carrier_id"].astype(str).isin(carrier_ids)
        missing_reason = ~returns["return_reason_id"].astype(str).isin(reason_ids)
        for code, mask in (
            ("AD_CAMPAIGN_MISSING", missing_campaign),
            ("ATTRIBUTION_CAMPAIGN_MISSING", missing_attribution_campaign),
            ("SHIPMENT_CARRIER_MISSING", missing_carrier),
            ("TRACKING_CARRIER_MISSING", missing_tracking_carrier),
            ("RETURN_REASON_MISSING", missing_reason),
        ):
            if int(mask.sum()):
                issues.append(_issue("FATAL", code, "维表关联失败", int(mask.sum())))

        credit = attribution.groupby("sales_order_number", dropna=False)["attribution_credit"].sum()
        if int(credit.gt(1.0000001).sum()):
            issues.append(_issue("FATAL", "ATTRIBUTION_CREDIT_EXCEEDED", "单订单归因信用超过 1", int(credit.gt(1.0000001).sum())))
        invalid_clicks = ads["clicks"].gt(ads["impressions"])
        invalid_conversions = ads["conversions"].gt(ads["clicks"])
        if int(invalid_clicks.sum()):
            issues.append(_issue("FATAL", "CLICKS_EXCEED_IMPRESSIONS", "clicks 不能超过 impressions", int(invalid_clicks.sum())))
        if int(invalid_conversions.sum()):
            issues.append(_issue("FATAL", "CONVERSIONS_EXCEED_CLICKS", "conversions 不能超过 clicks", int(invalid_conversions.sum())))
        if not ads["billing_currency"].astype(str).eq("USD").all():
            issues.append(_issue("FATAL", "AD_CURRENCY_NOT_USD", "广告 ROAS 必须使用 USD 花费和收入"))
        invalid_return_qty = returns["return_quantity"].gt(returns["original_order_quantity"])
        invalid_refund = returns["refund_amount"].gt(returns["original_line_sales_amount"] + 0.01)
        if int(invalid_return_qty.sum()):
            issues.append(_issue("FATAL", "RETURN_QUANTITY_EXCEEDED", "退款数量超过购买数量", int(invalid_return_qty.sum())))
        if int(invalid_refund.sum()):
            issues.append(_issue("FATAL", "REFUND_AMOUNT_EXCEEDED", "退款金额超过订单行金额", int(invalid_refund.sum())))

        event_sorted = tracking.sort_values(["shipment_id", "event_sequence"])
        timestamp_order = pd.to_datetime(event_sorted["event_timestamp"], errors="coerce").groupby(event_sorted["shipment_id"]).diff().dt.total_seconds()
        if int(timestamp_order.le(0).sum()):
            issues.append(_issue("FATAL", "TRACKING_TIME_NOT_STRICT", "物流事件必须严格按时间排序", int(timestamp_order.le(0).sum())))
        duplicate_sequence = tracking.duplicated(["shipment_id", "event_sequence"], keep=False)
        if int(duplicate_sequence.sum()):
            issues.append(_issue("FATAL", "TRACKING_SEQUENCE_DUPLICATE", "包裹事件序号必须唯一", int(duplicate_sequence.sum())))
        customs = tracking["event_code"].astype(str).str.contains("CUSTOMS", case=False, na=False)
        invalid_customs = customs & ~tracking["cross_border_flag"].astype(bool)
        if int(invalid_customs.sum()):
            issues.append(_issue("FATAL", "DOMESTIC_CUSTOMS_EVENT", "清关事件只允许出现在跨境包裹", int(invalid_customs.sum())))

        delivery_by_shipment = shipments.set_index("shipment_id")["actual_delivery_date"]
        return_delivery = pd.to_datetime(returns["shipment_id"].map(delivery_by_shipment), errors="coerce")
        return_request = pd.to_datetime(returns["return_request_date"], errors="coerce")
        invalid_return_time = return_delivery.notna() & return_request.le(return_delivery)
        if int(invalid_return_time.sum()):
            issues.append(_issue("FATAL", "RETURN_BEFORE_DELIVERY", "退货必须发生在签收之后", int(invalid_return_time.sum())))

        origins = pd.concat([frame.get("data_origin", pd.Series(dtype=str)) for frame in frames.values()], ignore_index=True)
        if not origins.astype(str).eq("synthetic_extension").all():
            issues.append(_issue("WARNING", "MIXED_DATA_ORIGIN", "扩展文件包含非模拟来源，展示时仍需逐行标识"))
        issues.append(_issue("WARNING", "SIMULATED_DATA", "广告、退款和物流是模拟扩展数据，不得展示为真实经营数据"))
        return {"issues": issues, "association_rates": rates}

    def _persist_business_data(
        self,
        dataset_id: str,
        order_load,
        frames: dict[str, pd.DataFrame],
        validation: dict[str, Any],
        root: Path,
    ) -> dict[str, Any]:
        generated = next((str(frame["generator_version"].iloc[0]) for frame in frames.values() if "generator_version" in frame and not frame.empty), "unknown")
        extension_hashes = [hashlib.sha256((root / name).read_bytes()).hexdigest() for name in IMPORT_ORDER]
        extension_digest = hashlib.sha256("|".join(extension_hashes).encode("ascii")).hexdigest()
        order_batch_id = "batch_aw_{}".format(order_load.loaded.metadata["sha256"][:16])
        batch_id = "batch_ext_{}".format(extension_digest[:16])
        now = datetime.now(timezone.utc).isoformat()
        inserted_total = 0
        duplicate_total = 0

        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            self._insert_batch(connection, order_batch_id, dataset_id, "adventureworks_dw", "ORIGINAL", "4.0.0", now)
            self._insert_batch(connection, batch_id, dataset_id, "synthetic_extension", "MULTI_SCENARIO", generated, now)
            self._record_order_files(connection, dataset_id, order_batch_id, order_load.source_files, now)
            self._insert_order_keys(connection, dataset_id, order_batch_id, order_load.loaded.data)

            for filename in IMPORT_ORDER:
                frame = frames[filename].copy()
                spec = FILE_TYPES[filename]
                digest = hashlib.sha256((root / filename).read_bytes()).hexdigest()
                existing = connection.execute(
                    "SELECT inserted_row_count FROM import_files WHERE dataset_id=? AND file_sha256=? AND file_type=?",
                    (dataset_id, digest, spec.file_type),
                ).fetchone()
                if existing:
                    duplicate_total += len(frame)
                    continue
                prepared = self._prepare_frame(frame, spec.table, dataset_id, batch_id)
                before = connection.total_changes
                self._insert_frame(connection, spec.table, prepared)
                inserted = connection.total_changes - before
                duplicates = len(frame) - inserted
                inserted_total += inserted
                duplicate_total += duplicates
                connection.execute(
                    "INSERT INTO import_files (import_file_id, import_batch_id, dataset_id, filename, file_sha256, "
                    "file_type, grain_description, data_origin, scenario_id, generator_version, source_version, "
                    "source_row_count, inserted_row_count, duplicate_row_count, imported_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'synthetic_extension', 'MULTI_SCENARIO', ?, 'AdventureWorksDW synthetic extension v1', ?, ?, ?, ?)",
                    (
                        "impf_{}".format(hashlib.sha256((dataset_id + digest + spec.file_type).encode()).hexdigest()[:24]),
                        batch_id, dataset_id, filename, digest, spec.file_type, spec.grain, generated,
                        len(frame), inserted, duplicates, now,
                    ),
                )
            connection.execute(
                "UPDATE import_batches SET status='READY', completed_at=?, warning_count=?, error_count=? WHERE import_batch_id IN (?, ?)",
                (
                    now,
                    sum(item["severity"] == "WARNING" for item in validation["issues"]),
                    sum(item["severity"] == "FATAL" for item in validation["issues"]),
                    order_batch_id,
                    batch_id,
                ),
            )
            connection.commit()
        violations = foreign_key_violations(self.database_path)
        if violations:
            raise RuntimeError("v4 foreign key validation failed: {}".format(violations[:5]))
        return {
            "import_batch_id": batch_id,
            "inserted_rows": inserted_total,
            "duplicate_rows": duplicate_total,
            "generator_version": generated,
        }

    @staticmethod
    def _insert_batch(connection, batch_id, dataset_id, origin, scenario, generator, now) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO import_batches (import_batch_id, dataset_id, status, data_origin, scenario_id, "
            "generator_version, source_version, started_at) VALUES (?, ?, 'IMPORTING', ?, ?, ?, ?, ?)",
            (batch_id, dataset_id, origin, scenario, generator, "AdventureWorksDW", now),
        )

    @staticmethod
    def _record_order_files(connection, dataset_id, batch_id, source_files, now) -> None:
        for item in source_files:
            connection.execute(
                "INSERT OR IGNORE INTO import_files (import_file_id, import_batch_id, dataset_id, filename, file_sha256, "
                "file_type, grain_description, data_origin, scenario_id, generator_version, source_version, "
                "source_row_count, inserted_row_count, duplicate_row_count, imported_at) "
                "VALUES (?, ?, ?, ?, ?, 'adventureworks_source', 'headerless pipe-delimited source table', "
                "'adventureworks_dw', 'ORIGINAL', '4.0.0', 'AdventureWorksDW', 0, 0, 0, ?)",
                (
                    "impf_{}".format(hashlib.sha256((dataset_id + item["sha256"] + item["filename"]).encode()).hexdigest()[:24]),
                    batch_id, dataset_id, item["filename"], item["sha256"], now,
                ),
            )

    @staticmethod
    def _insert_order_keys(connection, dataset_id, batch_id, orders: pd.DataFrame) -> None:
        provenance = (batch_id, "adventureworks_dw", "ORIGINAL", "4.0.0")
        connection.executemany(
            "INSERT OR IGNORE INTO business_orders VALUES (?, ?, ?, ?, ?, ?)",
            [(dataset_id, order, *provenance) for order in orders["sales_order_number"].astype(str).drop_duplicates()],
        )
        connection.executemany(
            "INSERT OR IGNORE INTO business_order_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (dataset_id, str(row.sales_order_number), int(row.sales_order_line_number), str(row.record_id), *provenance)
                for row in orders[["sales_order_number", "sales_order_line_number", "record_id"]].itertuples(index=False)
            ],
        )

    @staticmethod
    def _prepare_frame(frame: pd.DataFrame, table: str, dataset_id: str, batch_id: str) -> pd.DataFrame:
        output = frame.copy()
        output["dataset_id"] = dataset_id
        output["import_batch_id"] = batch_id
        if table == "dim_campaign":
            output["source_campaign_id"] = output["campaign_id"]
        elif table == "dim_carrier":
            output["source_carrier_id"] = output["carrier_id"]
        elif table == "dim_return_reason":
            output["source_return_reason_id"] = output["return_reason_id"]
        elif table == "fact_ad_performance_daily":
            output = output.rename(columns={"spend": "spend_usd"})
            output["source_campaign_id"] = output["campaign_id"]
            output["source_ad_date"] = output["ad_date"]
        elif table == "bridge_order_attribution":
            output["source_attribution_id"] = output["attribution_id"]
            output["source_sales_order_number"] = output["sales_order_number"]
        elif table == "fact_shipments":
            output["source_shipment_id"] = output["shipment_id"]
            output["source_sales_order_number"] = output["sales_order_number"]
        elif table == "fact_returns":
            output["source_return_id"] = output["return_id"]
            output["source_sales_order_number"] = output["sales_order_number"]
            output["source_sales_order_line_number"] = output["sales_order_line_number"]
        elif table == "fact_tracking_events":
            output["source_tracking_event_id"] = output["tracking_event_id"]
            output["source_shipment_id"] = output["shipment_id"]
        return output.loc[:, TABLE_COLUMNS[table]]

    @staticmethod
    def _insert_frame(connection, table: str, frame: pd.DataFrame) -> None:
        columns = TABLE_COLUMNS[table]
        sql = "INSERT OR IGNORE INTO {} ({}) VALUES ({})".format(
            table,
            ", ".join('"{}"'.format(column) for column in columns),
            ", ".join("?" for _ in columns),
        )
        rows = [tuple(_clean_sql_value(value) for value in row) for row in frame.itertuples(index=False, name=None)]
        connection.executemany(sql, rows)

"""Application service joining AutoClean contracts, FX, modules, and filters."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

from autoclean.analytics import (
    AnalysisBundle,
    AnalysisStatus,
    CsvFxProvider,
    FallbackFxProvider,
    FrankfurterFxProvider,
    FxConverter,
    ModuleResult,
    PipelineRunner,
    ValidationIssue,
    SQLiteStorageError,
    load_tabular,
    prepare_context,
)

from .contract import ECOMMERCE_CONTRACT, domain_issues
from .database import CrossBorderDatabase, SQLAnalysisRepository
from .decision import resolve_market_field
from .modules import amount_column, build_modules
from .data_quality import assess_business_quality
from .metrics import MetricsEngine, build_scope_id
from .phase2_catalogs import ANOMALY_RULES, METRICS_CATALOG, RECOMMENDATION_RULES
from .phase2_models import (
    AnalysisArtifacts, AnalysisRequest, CrossBorderAnalysisBundle,
)
from .phase2_storage import ArtifactStore
from .opportunities import OpportunityEngine
from .anomalies import RulesEngine
from .diagnosis import DiagnosisEngine
from .recommendations_v2 import RecommendationEngine
from .insights import InsightEngine


class AnalysisPipelineError(RuntimeError):
    """A failed analysis must be visible to callers, never silently downgraded."""


def _apply_metric_snapshot_adapter(bundle, snapshots) -> None:
    """Keep legacy result shapes while making registered snapshots authoritative."""
    selection = {
        item.metric_id: item.current_value for item in snapshots
        if item.entity_type == "global" and item.entity_id == "__all__" and item.period_type == "selection"
    }
    overview = bundle.results.get("overview")
    if overview and overview.status == AnalysisStatus.SUCCESS:
        mapping = {
            "gmv": "gmv", "orders": "orders", "customers": "customers", "units": "units",
            "aov": "aov", "profit": "profit_amount", "profit_margin": "profit_rate",
            "return_rate": "return_rate",
        }
        for metric_id, key in mapping.items():
            if metric_id in selection:
                value = selection[metric_id]
                overview.data[key] = int(value) if metric_id in {"orders", "customers", "units"} and value is not None else value
    sales = bundle.results.get("sales")
    if sales and sales.status == AnalysisStatus.SUCCESS and isinstance(sales.data.get("monthly"), pd.DataFrame):
        monthly = sales.data["monthly"].copy()
        month_snapshots = [
            item for item in snapshots
            if item.entity_type == "global" and item.period_type == "month"
            and item.metric_id in {"gmv", "orders", "aov", "profit", "profit_margin"}
        ]
        if month_snapshots and not monthly.empty:
            values = pd.DataFrame([
                {"month": item.period_start[:7], "metric_id": item.metric_id, "value": item.current_value}
                for item in month_snapshots
            ]).pivot(index="month", columns="metric_id", values="value").reset_index()
            values = values.rename(columns={"profit_margin": "profit_rate"})
            monthly = monthly.drop(columns=[column for column in values.columns if column != "month" and column in monthly], errors="ignore").merge(values, on="month", how="left")
            sales.data["monthly"] = monthly


class AnalysisService:
    def __init__(
        self,
        cache_dir: Optional[Any] = None,
        database_path: Optional[Any] = "database/ecommerce.db",
        backend: str = "sql",
    ):
        self.cache_dir = cache_dir
        if backend not in {"sql", "pandas"}:
            raise ValueError("backend must be 'sql' or 'pandas'")
        self.backend = backend
        self.database_path = database_path

    def prepare(
        self,
        source: Any,
        filename: Optional[str] = None,
        mapping: Optional[Mapping[str, str]] = None,
        source_currency: Optional[str] = None,
        target_currency: str = "CNY",
        fx_rates: Optional[Any] = None,
        online_fx: bool = True,
    ):
        loaded = load_tabular(source, filename=filename)
        return self.prepare_loaded(
            loaded,
            mapping=mapping,
            source_currency=source_currency,
            target_currency=target_currency,
            fx_rates=fx_rates,
            online_fx=online_fx,
        )

    def prepare_loaded(
        self,
        loaded,
        mapping: Optional[Mapping[str, str]] = None,
        source_currency: Optional[str] = None,
        target_currency: str = "CNY",
        fx_rates: Optional[Any] = None,
        online_fx: bool = True,
        contract=None,
    ):
        context = prepare_context(
            loaded,
            contract or ECOMMERCE_CONTRACT,
            mapping=mapping,
            semantic_overrides={"profit_amount": "order_profit_amount"},
        )
        context.issues.extend(domain_issues(context.analysis_data))
        context.metadata.update({
            "source_currency": source_currency.upper() if source_currency else None,
            "target_currency": target_currency.upper() if target_currency else None,
        })
        if context.fatal_issues:
            return context

        frame = context.analysis_data.copy()
        if "currency" not in frame:
            if not source_currency:
                context.issues.append(ValidationIssue(
                    "FATAL", "SOURCE_CURRENCY_REQUIRED", "数据没有currency字段，必须确认全表源币种"
                ))
                return context
            frame["currency"] = source_currency.upper()
        elif source_currency:
            frame["currency"] = frame["currency"].fillna(source_currency.upper())

        amount_fields = [
            field for field in ("price", "total_amount", "shipping_cost", "profit_amount", "cost_amount", "refund_amount", "ad_spend")
            if field in frame
        ]
        providers = []
        if fx_rates is not None:
            providers.append(CsvFxProvider(fx_rates))
        if online_fx:
            providers.append(FrankfurterFxProvider(cache_dir=self.cache_dir))
        provider = FallbackFxProvider(providers)
        converted, rates_used, fx_issues = FxConverter(provider).convert(
            frame, "order_date", "currency", amount_fields, target_currency.upper()
        )
        context.analysis_data = converted
        context.issues.extend(fx_issues)
        context.metadata["fx_complete"] = not any(issue.code == "FX_COVERAGE_INCOMPLETE" for issue in fx_issues)
        context.metadata["fx_rates"] = rates_used
        context.metadata["fx_provider"] = ", ".join(sorted(converted.fx_source.dropna().astype(str).unique()))
        return context

    def persist(self, context):
        if self.backend != "sql":
            return None
        if self.database_path is None:
            raise SQLiteStorageError("SQL backend requires a database path")
        return CrossBorderDatabase(self.database_path).persist(context)

    def run(
        self,
        context,
        filters: Optional[Dict[str, Any]] = None,
        request: Optional[AnalysisRequest] = None,
    ):
        if request is None:
            request = AnalysisRequest(filters=dict(filters or {}))
        elif filters:
            raise ValueError("Pass filters through AnalysisRequest or filters, not both")
        active_filters = dict(request.filters)
        filtered = context.analysis_data
        applied = {}
        for key, value in active_filters.items():
            if value in (None, [], ()) or key not in filtered:
                continue
            if key == "order_date" and isinstance(value, (tuple, list)) and len(value) == 2:
                start, end = pd.Timestamp(value[0]), pd.Timestamp(value[1])
                filtered = filtered[filtered[key].between(start, end)]
                applied[key] = [start.date().isoformat(), end.date().isoformat()]
            else:
                values = value if isinstance(value, (list, tuple, set)) else [value]
                filtered = filtered[filtered[key].isin(values)]
                applied[key] = list(values)
        run_context = replace(context, analysis_data=filtered.copy(), metadata=dict(context.metadata))
        run_context.metadata["filters"] = applied
        repository = None
        if self.backend == "sql" and not run_context.fatal_issues:
            try:
                database = CrossBorderDatabase(self.database_path)
                stored = database.persist(context)
                market_field = resolve_market_field(run_context.analysis_data) or "region"
                repository = SQLAnalysisRepository(
                    database, stored, filters=active_filters, market_field=market_field
                )
                run_context.metadata.update(context.metadata)
                run_context.metadata["filters"] = applied
                run_context.metadata["market_dimension"] = market_field
            except Exception as exc:
                run_context.metadata.update({
                    "analysis_backend": "sql",
                    "storage_error": str(exc),
                })
                bundle = AnalysisBundle(
                    context=run_context,
                    results={
                        "dataset": ModuleResult(
                            "dataset",
                            AnalysisStatus.FATAL,
                            message="Database initialization failed: {}".format(exc),
                            error_type=type(exc).__name__,
                        )
                    },
                    generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
                )
                return CrossBorderAnalysisBundle(bundle, AnalysisArtifacts())
        elif self.backend == "pandas":
            run_context.metadata["analysis_backend"] = "pandas"
        phase2_future = None
        phase2_executor = None
        phase2_quality = None
        phase2_dataset_id = str(
            run_context.metadata.get("scope_dataset_id")
            or run_context.metadata.get("dataset_id")
            or context.metadata.get("sha256")
            or "unpersisted"
        )
        phase2_scope_id = build_scope_id(
            phase2_dataset_id, request, context.metadata.get("target_currency") or ""
        )
        store = (
            ArtifactStore(self.database_path)
            if self.backend == "sql" and self.database_path is not None and not run_context.fatal_issues
            else None
        )
        artifact_versions = {
            "metrics": "1.0.0", "anomaly_rules": "1.0.0",
            "diagnosis": "1.2.0", "recommendations": "1.1.0",
            "insights": "1.0.0", "quality": "1.1.1",
        }
        cached_artifacts = (
            store.load(
                phase2_scope_id,
                expected_catalog_versions=artifact_versions,
            )
            if store else None
        )
        if not run_context.fatal_issues and cached_artifacts is None:
            phase2_quality = assess_business_quality(run_context, phase2_dataset_id, phase2_scope_id)
            if self.backend == "sql" and run_context.metadata.get("fx_complete") is not False:
                phase2_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="phase2-metrics")
                phase2_future = phase2_executor.submit(
                    MetricsEngine(repository).run, run_context, phase2_dataset_id, phase2_scope_id,
                    request, phase2_quality[0], phase2_quality[3],
                )
        if run_context.metadata.get("fx_complete") is False:
            message = "汇率覆盖不完整，跨币种金额模块已跳过；请上传完整汇率表或重试在线来源"
            bundle = AnalysisBundle(
                context=run_context,
                results={
                    module.name: ModuleResult(module.name, AnalysisStatus.SKIPPED, message=message)
                    for module in build_modules(repository, request.topic)
                },
                generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
            )
        else:
            bundle = PipelineRunner(build_modules(repository, request.topic)).run(run_context)
        bundle.metadata.update({
            "filters": applied,
            "fx_rates": context.metadata.get("fx_rates", pd.DataFrame()),
            "analysis_backend": self.backend,
            "database_schema_version": run_context.metadata.get("database_schema_version"),
            "dataset_id": run_context.metadata.get("dataset_id"),
            "query_runs": repository.query_runs if repository else [],
            "market_dimension": resolve_market_field(run_context.analysis_data),
            "product_detail_queries": [
                "product_detail_summary", "product_detail_monthly",
                "product_detail_market", "product_detail_customers",
            ],
            "artifact_store_path": str(Path(self.database_path).resolve()) if self.database_path is not None else None,
        })
        if cached_artifacts is not None:
            run_context.metadata["scope_cache"] = "HIT"
            bundle.metadata.update({
                "scope_id": phase2_scope_id,
                "analysis_request": request.to_dict(),
                "scope_cache": "HIT",
            })
            _apply_metric_snapshot_adapter(bundle, cached_artifacts.metric_snapshots)
            return CrossBorderAnalysisBundle(bundle, cached_artifacts)
        artifacts = AnalysisArtifacts(metric_definitions=list(METRICS_CATALOG))
        artifacts.anomaly_rules = list(ANOMALY_RULES)
        artifacts.recommendation_rules = list(RECOMMENDATION_RULES)
        dataset_id = phase2_dataset_id
        scope_id = phase2_scope_id
        bundle.metadata.update({"scope_id": scope_id, "analysis_request": request.to_dict()})
        if run_context.fatal_issues:
            quality = phase2_quality or assess_business_quality(run_context, dataset_id, scope_id)
            (
                artifacts.data_quality,
                artifacts.data_quality_dimensions,
                artifacts.field_quality,
                artifacts.analysis_capability,
                artifacts.data_improvement_plan,
                artifacts.unsupported_conclusions,
            ) = quality
            return CrossBorderAnalysisBundle(bundle, artifacts)
        if store:
            store.begin_run(scope_id, dataset_id, request, artifact_versions)
        try:
            quality = phase2_quality or assess_business_quality(run_context, dataset_id, scope_id)
            (
                artifacts.data_quality,
                artifacts.data_quality_dimensions,
                artifacts.field_quality,
                artifacts.analysis_capability,
                artifacts.data_improvement_plan,
                artifacts.unsupported_conclusions,
            ) = quality
            if run_context.metadata.get("fx_complete") is not False:
                snapshots, assessments, evidence = (
                    phase2_future.result()
                    if phase2_future is not None
                    else MetricsEngine(repository).run(
                        run_context, dataset_id, scope_id, request, artifacts.data_quality,
                        artifacts.analysis_capability,
                    )
                )
                artifacts.metric_snapshots = snapshots
                artifacts.entity_assessments = assessments
                artifacts.evidence = evidence
                artifacts.anomalies = RulesEngine().run(snapshots, artifacts.data_quality)
                artifacts.diagnoses = DiagnosisEngine().run(
                    artifacts.anomalies, snapshots, artifacts.data_quality,
                )
                artifacts.recommendations = RecommendationEngine().run(
                    artifacts.diagnoses, artifacts.anomalies, artifacts.data_quality, snapshots,
                )
                artifacts.insights = InsightEngine().run(
                    artifacts.anomalies, artifacts.diagnoses, artifacts.recommendations,
                    artifacts.data_quality, artifacts.analysis_capability,
                )
                if request.analysis_mode == "full":
                    (
                        artifacts.market_opportunities,
                        artifacts.product_opportunities,
                        artifacts.action_items,
                        artifacts.opportunity_summary,
                    ) = OpportunityEngine().run(run_context, artifacts)
                _apply_metric_snapshot_adapter(bundle, snapshots)
            if store:
                store.save(scope_id, artifacts)
            bundle.metadata["query_runs"] = repository.query_runs if repository else []
        except Exception as exc:
            if store:
                store.fail_run(scope_id, exc)
            raise AnalysisPipelineError(
                "Phase 2 analysis failed for scope {}: {}".format(scope_id, exc)
            ) from exc
        finally:
            if phase2_executor is not None:
                phase2_executor.shutdown(wait=True)
        return CrossBorderAnalysisBundle(bundle, artifacts)

    def product_detail(self, bundle, product_id: str) -> Dict[str, Any]:
        """Return one product's decision evidence without changing the analysis bundle."""
        product_id = str(product_id)
        product_result = bundle.results.get("product")
        products = product_result.data.get("products", pd.DataFrame()) if product_result and product_result.data else pd.DataFrame()
        product_row = products.loc[products["product_id"].astype(str).eq(product_id)] if not products.empty else pd.DataFrame()
        missing_fields = [
            field for field in ("product_name", "profit_amount", "returned", "customer_id")
            if field not in bundle.context.analysis_data
        ]

        if self.backend == "sql":
            dataset_id = bundle.metadata.get("dataset_id")
            if not dataset_id or self.database_path is None:
                raise SQLiteStorageError("Product detail requires a persisted dataset")
            database = CrossBorderDatabase(self.database_path)
            stored = database.store.get_dataset(dataset_id)
            if stored is None:
                raise SQLiteStorageError("Dataset not found: {}".format(dataset_id))
            repository = SQLAnalysisRepository(
                database,
                stored,
                filters=bundle.metadata.get("filters", {}),
                market_field=bundle.metadata.get("market_dimension") or "region",
            )
            summary_frame = repository.product_detail("product_detail_summary", product_id)
            monthly = repository.product_detail("product_detail_monthly", product_id)
            market_mix = repository.product_detail("product_detail_market", product_id)
            customer_rows = repository.product_detail("product_detail_customers", product_id)
            query_runs = repository.query_runs
        else:
            frame = bundle.context.analysis_data.copy()
            filters = bundle.metadata.get("filters", {})
            date_range = filters.get("order_date")
            if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
                frame = frame.loc[frame.order_date.between(pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]))]
            frame = frame.loc[frame.product_id.astype(str).eq(product_id)].copy()
            summary_frame = product_row.copy()
            frame["month"] = frame.order_date.dt.to_period("M").astype(str)
            amount = amount_column(frame)
            monthly_agg = {"orders": ("order_id", "nunique"), "gmv": (amount, "sum")}
            if "quantity" in frame:
                monthly_agg["units"] = ("quantity", "sum")
            if "profit_amount" in frame:
                profit = "profit_amount_base" if "profit_amount_base" in frame else "profit_amount"
                monthly_agg["profit"] = (profit, "sum")
            if "returned" in frame:
                monthly_agg["returned_orders"] = ("returned", "sum")
            monthly = frame.groupby("month").agg(**monthly_agg).reset_index() if not frame.empty else pd.DataFrame()
            market_field = resolve_market_field(frame)
            if market_field:
                label = "未标注国家" if market_field == "country" else "未标注区域"
                frame["market"] = frame[market_field].astype("string").str.strip().replace("", pd.NA).fillna(label)
                market_mix = frame.groupby("market").agg(
                    orders=("order_id", "nunique"),
                    customers=("customer_id", "nunique") if "customer_id" in frame else ("order_id", "size"),
                    gmv=(amount, "sum"),
                ).reset_index()
            else:
                market_mix = pd.DataFrame()
            customer_rows = frame.groupby("customer_id").agg(
                orders=("order_id", "nunique"), gmv=(amount, "sum")
            ).reset_index() if "customer_id" in frame else pd.DataFrame()
            query_runs = []

        summary = product_row.iloc[0].to_dict() if not product_row.empty else (
            summary_frame.iloc[0].to_dict() if not summary_frame.empty else {}
        )
        if not monthly.empty:
            for column in ("units", "profit", "returned_orders"):
                if column not in monthly:
                    monthly[column] = pd.NA
            monthly["profit_rate"] = monthly["profit"] / monthly["gmv"] if "profit_amount" not in missing_fields else pd.NA
            monthly["return_rate"] = monthly["returned_orders"] / monthly["orders"] if "returned" not in missing_fields else pd.NA
        if not market_mix.empty:
            market_mix["order_share"] = market_mix.orders / market_mix.orders.sum()
            market_mix["gmv_share"] = market_mix.gmv / market_mix.gmv.sum()

        customer_mix = pd.DataFrame()
        customer_result = bundle.results.get("customer")
        if not customer_rows.empty and customer_result and customer_result.data:
            segments = customer_result.data["customers"][["customer_id", "segment"]]
            joined = customer_rows.merge(segments, on="customer_id", how="left")
            customer_mix = joined.groupby("segment", dropna=False).agg(
                customers=("customer_id", "nunique"), orders=("orders", "sum"), gmv=("gmv", "sum")
            ).reset_index()
            customer_mix["gmv_share"] = customer_mix.gmv / customer_mix.gmv.sum()

        periods = int(monthly["month"].nunique()) if "month" in monthly else 0
        return {
            "summary": summary,
            "monthly": monthly.copy(deep=True),
            "market_mix": market_mix.copy(deep=True),
            "customer_mix": customer_mix.copy(deep=True),
            "periods": periods,
            "trend_available": periods >= 8,
            "missing_fields": tuple(missing_fields),
            "evidence": {
                "id": "product.detail.{}".format(product_id),
                "formula": "商品订单按当前固定分析周期聚合",
                "source_fields": tuple(field for field in (
                    "product_id", "product_name", "category", "order_date", "total_amount",
                    "profit_amount", "returned", "customer_id",
                ) if field in bundle.context.analysis_data),
                "sample_size": int(summary.get("orders", 0) or 0),
                "date_range": [summary.get("first_order"), summary.get("last_order")],
            },
            "query_runs": query_runs,
        }


def analyze_file(
    source: Any,
    filename: Optional[str] = None,
    source_currency: Optional[str] = None,
    target_currency: str = "CNY",
    **kwargs
):
    service = AnalysisService(
        cache_dir=kwargs.pop("cache_dir", None),
        database_path=kwargs.pop("database_path", "database/ecommerce.db"),
        backend=kwargs.pop("backend", "sql"),
    )
    request = kwargs.pop("request", None)
    context = service.prepare(
        source,
        filename=filename,
        source_currency=source_currency,
        target_currency=target_currency,
        **kwargs
    )
    return service.run(context, request=request)

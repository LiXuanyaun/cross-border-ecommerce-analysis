"""Application service joining AutoClean contracts, FX, modules, and filters."""
from dataclasses import replace
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
    load_tabular,
    prepare_context,
)

from .contract import ECOMMERCE_CONTRACT, domain_issues
from .modules import ALL_MODULES
from .recommendations import build_recommendations


class AnalysisService:
    def __init__(self, cache_dir: Optional[Any] = None):
        self.cache_dir = cache_dir

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
        context = prepare_context(
            loaded,
            ECOMMERCE_CONTRACT,
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

        amount_fields = [field for field in ("price", "total_amount", "shipping_cost", "profit_amount") if field in frame]
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

    def run(self, context, filters: Optional[Dict[str, Any]] = None):
        filtered = context.analysis_data
        applied = {}
        for key, value in (filters or {}).items():
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
        if run_context.metadata.get("fx_complete") is False:
            message = "汇率覆盖不完整，跨币种金额模块已跳过；请上传完整汇率表或重试在线来源"
            bundle = AnalysisBundle(
                context=run_context,
                results={
                    module.name: ModuleResult(module.name, AnalysisStatus.SKIPPED, message=message)
                    for module in ALL_MODULES
                },
                generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
            )
        else:
            bundle = PipelineRunner(ALL_MODULES).run(run_context)
        bundle.recommendations = build_recommendations(bundle)
        bundle.metadata.update({
            "filters": applied,
            "fx_rates": context.metadata.get("fx_rates", pd.DataFrame()),
        })
        return bundle


def analyze_file(
    source: Any,
    filename: Optional[str] = None,
    source_currency: Optional[str] = None,
    target_currency: str = "CNY",
    **kwargs
):
    service = AnalysisService(cache_dir=kwargs.pop("cache_dir", None))
    context = service.prepare(
        source,
        filename=filename,
        source_currency=source_currency,
        target_currency=target_currency,
        **kwargs
    )
    return service.run(context)

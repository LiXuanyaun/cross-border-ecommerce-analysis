from __future__ import annotations

from typing import Any

from crossborder_analytics.decision_brief import build_decision_brief

from .runtime import _clean


class AgentContextBuilder:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def build(
        self,
        dataset_id: str,
        question: str,
        start: str | None = None,
        end: str | None = None,
        market: str | None = None,
        category: str | None = None,
    ) -> tuple[dict[str, Any], Any]:
        overview, bundle = self.runtime.overview(dataset_id, start, end)
        if market or category:
            bundle = self.runtime.bundle(dataset_id, start, end, market, category)
        lowered = question.lower()
        tool_names = ["get_dataset_profile", "get_data_quality", "query_metrics"]
        tool_names.extend(["get_metric", "compare_periods"])
        decision_requested = any(token in lowered for token in ("建议", "行动", "怎么办", "报告"))
        diagnosis_requested = decision_requested or any(
            token in lowered for token in ("异常", "下降", "风险", "为什么", "原因", "问题")
        )
        if diagnosis_requested:
            tool_names.extend(["list_anomalies", "get_diagnosis", "get_evidence"])
        if decision_requested:
            tool_names.extend([
                "create_task", "get_recommendations", "generate_report",
                "generate_review_report", "explain_limitation",
            ])
        quality = bundle.artifacts.data_quality.to_dict() if bundle.artifacts.data_quality else None
        insights = [item.to_dict() for item in bundle.artifacts.insights[:5]]
        evidence = [item.to_dict() for item in bundle.artifacts.evidence[:3]]
        recommendations = [item.to_dict() for item in bundle.artifacts.recommendations[:5]]
        decision_brief = build_decision_brief(bundle.artifacts, bundle.metadata)
        anomaly_by_id = {item.anomaly_id: item for item in bundle.artifacts.anomalies}
        trace = []
        for insight in bundle.artifacts.insights[:5]:
            anomaly = anomaly_by_id.get(insight.anomaly_id or "")
            trace.append({
                "insight_id": insight.insight_id,
                "anomaly_id": insight.anomaly_id,
                "rule_id": anomaly.rule_id if anomaly else None,
                "rule_version": anomaly.rule_version if anomaly else None,
                "metric_id": insight.metric_id,
                "evidence_ids": list(insight.evidence_ids),
            })
        execution_context = {
            "question": question,
            "dataset": {
                "dataset_id": dataset_id,
                "name": self.runtime.scenario(dataset_id).name,
            },
            "period": overview["period"],
            "filters": {"start": start, "end": end, "market": market, "category": category},
            "scope_id": bundle.metadata.get("scope_id"),
            "overview": overview,
            "quality": quality,
            "insights": insights,
            "evidence": evidence,
            "recommendations": recommendations,
            "decision_brief": decision_brief,
            "trace": trace,
        }
        agent_plan = self.runtime.agent_tools.plan(question, execution_context)
        planned_tools = [
            tool
            for step in agent_plan
            for tool in step.get("tools", [])
        ]
        tool_names = list(dict.fromkeys(planned_tools or tool_names))
        tool_observations = self.runtime.agent_tools.execute_plan(agent_plan, execution_context)
        return _clean({
            "question": question,
            "dataset": {
                "dataset_id": dataset_id,
                "name": self.runtime.scenario(dataset_id).name,
            },
            "period": overview["period"],
            "filters": {"start": start, "end": end, "market": market, "category": category},
            "scope_id": bundle.metadata.get("scope_id"),
            "tools": list(dict.fromkeys(tool_names)),
            "agent_plan": agent_plan,
            "overview": overview,
            "quality": quality,
            "insights": insights,
            "evidence": evidence,
            "recommendations": recommendations,
            "decision_brief": decision_brief,
            "trace": trace,
            "tool_observations": tool_observations,
        }), bundle

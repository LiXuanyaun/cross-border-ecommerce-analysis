from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AgentToolResult:
    tool: str
    status: str
    payload: dict[str, Any]
    evidence_ids: list[str]
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.payload)
        payload.setdefault("name", self.tool)
        data = {
            "tool": self.tool,
            "status": self.status,
            "payload": payload,
            "evidence_ids": list(self.evidence_ids),
        }
        if self.message:
            data["message"] = self.message
        return data


@dataclass(frozen=True)
class AgentPlanStep:
    step_id: str
    title: str
    goal: str
    tools: list[str]
    depends_on: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "goal": self.goal,
            "tools": list(self.tools),
            "depends_on": list(self.depends_on),
            "status": "PENDING",
        }


class AgentToolRegistry:
    def __init__(self, tools: dict[str, Callable[[dict[str, Any]], AgentToolResult]]) -> None:
        self._tools = tools

    def names(self) -> list[str]:
        return list(self._tools)

    def plan(self, question: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        lowered = question.lower()
        wants_diagnosis = any(
            token in lowered
            for token in ("异常", "下降", "风险", "为什么", "原因", "问题", "driver", "risk")
        )
        wants_action = wants_diagnosis or any(
            token in lowered
            for token in ("建议", "行动", "怎么办", "报告", "task", "recommend", "action")
        )
        wants_limitations = wants_action or any(
            token in lowered
            for token in ("限制", "缺少", "不能", "不可", "limitation")
        )
        steps = [
            AgentPlanStep(
                "plan-1",
                "确认数据范围",
                "确认数据集、时间范围、筛选条件和数据质量是否支持回答",
                ["get_dataset_profile", "get_data_quality"],
                [],
            ),
            AgentPlanStep(
                "plan-2",
                "读取经营指标",
                "读取注册指标和可比较周期，建立事实基线",
                ["query_metrics", "get_metric", "compare_periods"],
                ["plan-1"],
            ),
        ]
        if wants_diagnosis:
            steps.append(AgentPlanStep(
                "plan-3",
                "诊断异常驱动",
                "从正式异常、诊断和证据链中提取可解释驱动",
                ["list_anomalies", "get_diagnosis", "get_evidence"],
                ["plan-2"],
            ))
        if wants_action:
            steps.append(AgentPlanStep(
                "plan-4",
                "生成行动草案",
                "基于已验证证据生成建议、任务草稿和报告摘要",
                ["create_task", "get_recommendations", "generate_report", "generate_review_report"],
                ["plan-3" if wants_diagnosis else "plan-2"],
            ))
        if wants_limitations:
            steps.append(AgentPlanStep(
                "plan-5",
                "声明分析边界",
                "列出缺失字段、不可回答问题和不能声称的因果结论",
                ["explain_limitation"],
                [steps[-1].step_id],
            ))
        return [step.to_dict() for step in steps]

    def execute(self, tool_names: list[str], context: dict[str, Any]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for name in tool_names:
            handler = self._tools.get(name)
            if handler is None:
                observations.append(AgentToolResult(
                    tool=name,
                    status="SKIPPED",
                    payload={},
                    evidence_ids=[],
                    message="未注册工具",
                ).to_dict())
                continue
            observations.append(handler(context).to_dict())
        return observations

    def execute_plan(self, plan: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        completed: set[str] = set()
        for step in plan:
            dependencies = [str(item) for item in step.get("depends_on", [])]
            step_tools = [str(item) for item in step.get("tools", [])]
            if any(dependency not in completed for dependency in dependencies):
                for name in step_tools:
                    observation = AgentToolResult(
                        tool=name,
                        status="SKIPPED",
                        payload={"plan_step_id": step.get("step_id"), "plan_step": step.get("title")},
                        evidence_ids=[],
                        message="计划依赖未完成",
                    ).to_dict()
                    observations.append(observation)
                continue
            for observation in self.execute(step_tools, context):
                observation["plan_step_id"] = step.get("step_id")
                observation["plan_step"] = step.get("title")
                observation["payload"]["plan_step_id"] = step.get("step_id")
                observation["payload"]["plan_step"] = step.get("title")
                observations.append(observation)
            completed.add(str(step.get("step_id")))
            step["status"] = "COMPLETED"
        return observations


def build_agent_tool_registry() -> AgentToolRegistry:
    def dataset_profile(context: dict[str, Any]) -> AgentToolResult:
        dataset = context.get("dataset", {})
        period = context.get("period", {})
        filters = context.get("filters", {})
        payload = {"dataset": dataset, "period": period, "filters": filters, "scope_id": context.get("scope_id")}
        return AgentToolResult("get_dataset_profile", "SUCCESS", payload, [])

    def data_quality(context: dict[str, Any]) -> AgentToolResult:
        quality = context.get("quality") or {}
        flattened = [
            evidence_id
            for item in context.get("trace", [])
            for evidence_id in item.get("evidence_ids", [])
            if evidence_id
        ]
        return AgentToolResult("get_data_quality", "SUCCESS", {"quality": quality}, flattened)

    def query_metrics(context: dict[str, Any]) -> AgentToolResult:
        overview = context.get("overview", {})
        metrics = overview.get("kpis", []) if isinstance(overview, dict) else []
        evidence_ids = [row.get("evidence_id") for row in metrics if row.get("evidence_id")]
        return AgentToolResult("query_metrics", "SUCCESS", {"metrics": metrics[:8]}, evidence_ids)

    def get_metric(context: dict[str, Any]) -> AgentToolResult:
        overview = context.get("overview", {})
        metrics = overview.get("kpis", []) if isinstance(overview, dict) else []
        target = metrics[0] if metrics else {}
        return AgentToolResult("get_metric", "SUCCESS", {"metric": target}, [target.get("evidence_id")] if target.get("evidence_id") else [])

    def compare_periods(context: dict[str, Any]) -> AgentToolResult:
        overview = context.get("overview", {})
        return AgentToolResult(
            "compare_periods",
            "SUCCESS",
            {"current_period": overview.get("period"), "comparison_period": overview.get("comparison_period")},
            [],
        )

    def list_anomalies(context: dict[str, Any]) -> AgentToolResult:
        brief = context.get("decision_brief", {})
        cases = brief.get("cases", []) if isinstance(brief, dict) else []
        evidence_ids = [row.get("evidence_id") for case in cases for row in case.get("evidence", []) if row.get("evidence_id")]
        return AgentToolResult("list_anomalies", "SUCCESS", {"cases": cases[:5]}, evidence_ids)

    def get_diagnosis(context: dict[str, Any]) -> AgentToolResult:
        brief = context.get("decision_brief", {})
        cases = brief.get("cases", []) if isinstance(brief, dict) else []
        drivers = [driver for case in cases for driver in case.get("drivers", [])[:3]]
        evidence_ids = [row.get("evidence_id") for case in cases for row in case.get("evidence", []) if row.get("evidence_id")]
        return AgentToolResult("get_diagnosis", "SUCCESS", {"drivers": drivers[:8]}, evidence_ids)

    def get_evidence(context: dict[str, Any]) -> AgentToolResult:
        evidence = context.get("evidence", [])
        evidence_ids = [row.get("evidence_id") for row in evidence if row.get("evidence_id")]
        return AgentToolResult("get_evidence", "SUCCESS", {"evidence": evidence[:8]}, evidence_ids)

    def create_task(context: dict[str, Any]) -> AgentToolResult:
        brief = context.get("decision_brief", {})
        actions = [action for case in brief.get("cases", []) for action in case.get("actions", [])[:1]]
        evidence_ids = [row.get("evidence_id") for case in brief.get("cases", []) for row in case.get("evidence", []) if row.get("evidence_id")]
        return AgentToolResult(
            "create_task",
            "SKIPPED",
            {"draft_tasks": actions[:5]},
            evidence_ids,
            "Agent 不自动创建任务；仅生成可复核任务草稿",
        )

    def get_recommendations(context: dict[str, Any]) -> AgentToolResult:
        recommendations = context.get("recommendations", [])
        evidence_ids = [row.get("evidence_id") for row in recommendations if row.get("evidence_id")]
        return AgentToolResult("get_recommendations", "SUCCESS", {"recommendations": recommendations[:8]}, evidence_ids)

    def generate_report(context: dict[str, Any], tool_name: str = "generate_report") -> AgentToolResult:
        report = {
            "scope_id": context.get("scope_id"),
            "period": context.get("period"),
            "case_count": len(context.get("decision_brief", {}).get("cases", [])),
        }
        return AgentToolResult(tool_name, "SUCCESS", report, [])

    def explain_limitation(context: dict[str, Any]) -> AgentToolResult:
        brief = context.get("decision_brief", {})
        return AgentToolResult(
            "explain_limitation",
            "SUCCESS",
            {"limitations": brief.get("limitations", []), "unavailable_metrics": brief.get("unavailable_metrics", [])},
            [],
        )

    return AgentToolRegistry({
        "get_dataset_profile": dataset_profile,
        "get_data_quality": data_quality,
        "query_metrics": query_metrics,
        "get_metric": get_metric,
        "compare_periods": compare_periods,
        "list_anomalies": list_anomalies,
        "get_diagnosis": get_diagnosis,
        "get_evidence": get_evidence,
        "create_task": create_task,
        "get_recommendations": get_recommendations,
        "generate_report": generate_report,
        "generate_review_report": lambda context: generate_report(context, "generate_review_report"),
        "explain_limitation": explain_limitation,
    })

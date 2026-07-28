from functools import lru_cache

from crossborder_analytics.decision_brief import _limitations
from crossborder_api.agent import AgentManager
from crossborder_api.runtime import AnalyticsRuntime


@lru_cache(maxsize=1)
def _context():
    runtime = AnalyticsRuntime()
    return runtime.agent_context("demo-all", "分析最近经营异常、驱动和建议")[0]


def test_decision_brief_is_ranked_unique_and_evidence_bound():
    brief = _context()["decision_brief"]

    assert brief["status"] == "SUCCESS"
    assert 1 <= len(brief["cases"]) <= 5
    object_keys = [
        (item["anomaly"]["object_type"], item["anomaly"]["object_name"], item["anomaly"]["metric_id"])
        for item in brief["cases"]
    ]
    summaries = [item["finding"]["summary"] for item in brief["cases"]]
    assert len(object_keys) == len(set(object_keys))
    assert len(summaries) == len(set(summaries))
    assert [item["rank"] for item in brief["cases"]] == list(range(1, len(brief["cases"]) + 1))

    for case in brief["cases"]:
        assert case["finding"]["main_object"] == case["anomaly"]["object_name"]
        assert case["chain"]["anomaly"]
        assert case["chain"]["drivers"]
        assert case["chain"]["evidence"]
        assert case["evidence"]
        assert all("evidence_id" not in row and "query_name" not in row for row in case["evidence"])
        contributions = [abs(item["impact_amount"]) for item in case["drivers"]]
        assert contributions == sorted(contributions, reverse=True)
        assert all(item["contribution_share"] is None or item["contribution_share"] >= 0 for item in case["drivers"])


def test_actions_are_executable_and_do_not_fabricate_expected_benefit():
    brief = _context()["decision_brief"]
    forbidden_starts = ("检查", "分析", "关注")
    unavailable = {item["metric"]: item for item in brief["unavailable_metrics"]}

    assert unavailable["广告 ROI"]["status"] == "SKIPPED"
    assert unavailable["CTR（点击率）"]["status"] == "SKIPPED"
    assert unavailable["CVR（转化率）"]["status"] == "SKIPPED"
    assert unavailable["库存周转"]["status"] == "SKIPPED"

    actions = [action for case in brief["cases"] for action in case["actions"]]
    assert actions
    for action in actions:
        assert not action["title"].startswith(forbidden_starts)
        assert not action["action"].startswith(forbidden_starts)
        assert len(action["steps"]) >= 2
        assert action["priority"].startswith("P")
        assert action["reason"]
        assert action["affected_object"]
        assert action["expected_benefit"]["status"] == "SKIPPED"
        assert action["expected_benefit"]["value"] is None
        assert "无法可靠估算" in action["expected_benefit"]["message"]


def test_agent_answer_hides_internal_evidence_identifiers():
    context = _context()
    answer = AgentManager._apply_answer_contract(
        AgentManager._deterministic_answer(context),
        context,
    )

    assert "关键发现" in answer
    assert "建议动作" in answer
    assert "业务证据" in answer
    assert "metric_facts" not in answer
    assert "ev_" not in answer
    assert "证据 ID" not in answer


def test_recommendation_request_cannot_skip_the_evidence_chain():
    context = _context()
    tools = context["tools"]
    plan_titles = [step["title"] for step in context["agent_plan"]]

    assert tools.index("query_metrics") < tools.index("list_anomalies")
    assert tools.index("list_anomalies") < tools.index("get_diagnosis")
    assert tools.index("get_diagnosis") < tools.index("get_evidence")
    assert tools.index("get_evidence") < tools.index("get_recommendations")
    assert plan_titles == [
        "确认数据范围",
        "读取经营指标",
        "诊断异常驱动",
        "生成行动草案",
        "声明分析边界",
    ]


def test_agent_context_exposes_structured_tool_observations():
    context = _context()
    observations = {item["tool"]: item for item in context["tool_observations"]}

    assert {
        "get_dataset_profile",
        "get_data_quality",
        "query_metrics",
        "get_metric",
        "compare_periods",
        "list_anomalies",
        "get_diagnosis",
        "get_evidence",
        "create_task",
        "get_recommendations",
        "generate_review_report",
        "explain_limitation",
    } <= set(observations)
    assert observations["create_task"]["status"] == "SKIPPED"
    assert observations["generate_review_report"]["status"] == "SUCCESS"
    assert observations["get_evidence"]["evidence_ids"]
    assert observations["get_evidence"]["plan_step_id"] == "plan-3"
    assert observations["get_recommendations"]["plan_step_id"] == "plan-4"


def test_limitations_preserve_statements_and_only_prefix_missing_context():
    limitations = _limitations(
        ["退货关联 GMV 不代表实际退款损失", "仅识别数据贡献关系", "缺少库存字段"],
        ["库存字段", "广告花费字段"],
    )

    assert limitations == [
        "退货关联 GMV 不代表实际退款损失",
        "仅识别数据贡献关系",
        "缺少库存字段",
        "缺少广告花费字段",
    ]

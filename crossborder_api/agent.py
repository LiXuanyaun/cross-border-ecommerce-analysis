from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import asyncio
import json
import os
import re
import sqlite3
import tomllib
import uuid
import time

import httpx


def _unique_text(values) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


@dataclass
class ProviderConfig:
    source: str
    provider_name: str
    base_url: str
    api_key: str
    model: str
    wire_api: str


class ProviderStore:
    def __init__(self, app_mode: str) -> None:
        self.app_mode = app_mode
        self.config: ProviderConfig | None = self._from_env()

    @staticmethod
    def _from_env() -> ProviderConfig | None:
        key = os.getenv("AI_API_KEY")
        base = os.getenv("AI_BASE_URL")
        model = os.getenv("AI_MODEL")
        if not key or not base or not model:
            return None
        return ProviderConfig(
            source="environment",
            provider_name="环境变量",
            base_url=base.rstrip("/"),
            api_key=key,
            model=model,
            wire_api=os.getenv("AI_WIRE_API", "responses"),
        )

    @staticmethod
    def ccswitch_path() -> Path:
        return Path.home() / ".cc-switch" / "cc-switch.db"

    def safe_status(self) -> dict[str, Any]:
        available = self.ccswitch_path().exists() and self.app_mode == "private"
        if self.config:
            return {
                "configured": True,
                "source": self.config.source,
                "provider_name": self.config.provider_name,
                "model": self.config.model,
                "wire_api": self.config.wire_api,
                "ccswitch_available": available,
                "message": "模型连接已配置",
            }
        return {
            "configured": False,
            "source": "none",
            "provider_name": None,
            "model": None,
            "wire_api": None,
            "ccswitch_available": available,
            "message": "演示分析可用；真实模型尚未配置",
        }

    def import_ccswitch(self) -> dict[str, Any]:
        if self.app_mode != "private":
            raise PermissionError("CC Switch 导入仅在本地私有模式可用")
        path = self.ccswitch_path()
        if not path.exists():
            raise FileNotFoundError("未发现 CC Switch 配置")
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT name, settings_config FROM providers WHERE app_type='codex' AND is_current=1 LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if not row:
            raise ValueError("CC Switch 没有当前 Codex provider")
        name, raw = row
        settings = json.loads(raw)
        config_text = settings.get("config", "")
        config = tomllib.loads(config_text) if config_text else {}
        provider_id = config.get("model_provider", "custom")
        provider = config.get("model_providers", {}).get(provider_id, {})
        base_url = str(provider.get("base_url") or "").rstrip("/")
        api_key = settings.get("auth", {}).get("OPENAI_API_KEY")
        model = str(config.get("model") or "")
        wire_api = str(provider.get("wire_api") or "responses")
        if not base_url.startswith(("http://", "https://")) or not api_key or not model:
            raise ValueError("当前 CC Switch provider 缺少 Base URL、Key 或模型")
        self.config = ProviderConfig("ccswitch", str(name), base_url, str(api_key), model, wire_api)
        return self.safe_status()

    async def synthesize(self, prompt: str) -> str | None:
        if not self.config:
            return None
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120) as client:
            if self.config.wire_api in {"chat", "chat_completions", "chat-completions"}:
                response = await client.post(
                    f"{self.config.base_url}/chat/completions",
                    headers=headers,
                    json={"model": self.config.model, "messages": [{"role": "user", "content": prompt}]},
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
            response = await client.post(
                f"{self.config.base_url}/responses",
                headers=headers,
                json={"model": self.config.model, "input": prompt},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("output_text"):
                return payload["output_text"]
            texts = []
            for output in payload.get("output", []):
                for content in output.get("content", []):
                    if content.get("text"):
                        texts.append(content["text"])
            return "\n".join(texts) or None


class AgentManager:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.provider = ProviderStore(runtime.app_mode)
        self.state = runtime.state_store
        self.sessions = self.state.load_sessions() if self.state else {}
        self.runs: dict[str, list[dict[str, Any]]] = {}
        self.done: set[str] = set()
        self._run_sessions: dict[str, str] = {}
        self._session_deadlines: dict[str, float] = {}
        self._demo_ttl_seconds = max(60, int(os.getenv("CROSSBORDER_DEMO_SESSION_TTL", "3600")))

    def _cleanup_expired(self) -> None:
        if self.runtime.app_mode != "demo":
            return
        now = time.monotonic()
        expired = [session_id for session_id, deadline in self._session_deadlines.items() if deadline <= now]
        for session_id in expired:
            self.sessions.pop(session_id, None)
            self._session_deadlines.pop(session_id, None)
            run_ids = [run_id for run_id, owner in self._run_sessions.items() if owner == session_id]
            for run_id in run_ids:
                self.runs.pop(run_id, None)
                self.done.discard(run_id)
                self._run_sessions.pop(run_id, None)

    def create_session(self, dataset_id: str) -> dict[str, Any]:
        self._cleanup_expired()
        session_id = f"session_{uuid.uuid4().hex[:16]}"
        self.sessions[session_id] = {
            "session_id": session_id,
            "dataset_id": dataset_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "messages": [],
        }
        if self.runtime.app_mode == "demo":
            self._session_deadlines[session_id] = time.monotonic() + self._demo_ttl_seconds
        if self.state:
            self.state.save_session(self.sessions[session_id])
        return self.sessions[session_id]

    def start(
        self, session_id: str, dataset_id: str, question: str,
        start: str | None = None, end: str | None = None,
        market: str | None = None, category: str | None = None,
    ) -> str:
        self._cleanup_expired()
        if session_id not in self.sessions:
            raise KeyError(session_id)
        if self.sessions[session_id]["dataset_id"] != dataset_id:
            raise ValueError("运行数据集必须与分析会话的数据集一致")
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        self.runs[run_id] = []
        self._run_sessions[run_id] = session_id
        if self.state:
            self.state.save_run(run_id, session_id, dataset_id, question)
        asyncio.create_task(self._execute(run_id, session_id, dataset_id, question, start, end, market, category))
        return run_id

    def _emit(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        event = {"type": event_type, "payload": payload}
        self.runs[run_id].append(event)
        if self.state:
            self.state.save_event(run_id, len(self.runs[run_id]) - 1, event)

    async def _execute(
        self, run_id: str, session_id: str, dataset_id: str, question: str,
        start: str | None = None, end: str | None = None,
        market: str | None = None, category: str | None = None,
    ) -> None:
        run_status = "SUCCESS"
        try:
            self._emit(run_id, "stage", {"stage": "理解问题", "status": "completed"})
            context, bundle = await asyncio.to_thread(
                self.runtime.agent_context, dataset_id, question, start, end, market, category,
            )
            context["conversation"] = self.sessions[session_id].get("messages", [])[-6:]
            self._emit(run_id, "plan", {"steps": context.get("agent_plan", [])})
            self._emit(run_id, "stage", {"stage": "数据分析", "status": "running"})
            observations = {item["tool"]: item for item in context.get("tool_observations", []) if item.get("tool")}
            for tool in context["tools"]:
                observation = observations.get(tool, {"tool": tool, "status": "SKIPPED", "payload": {}, "evidence_ids": []})
                self._emit(run_id, "tool", observation)
                await asyncio.sleep(0.05)
            self._emit(run_id, "stage", {"stage": "原因分析", "status": "completed"})
            if context.get("decision_brief", {}).get("status") != "SUCCESS":
                run_status = "SKIPPED"
            answer = self._deterministic_answer(context)
            if self.provider.config:
                model_context = {
                    "question": context.get("question"),
                    "conversation": context.get("conversation"),
                    "dataset": context.get("dataset"),
                    "period": context.get("period"),
                    "scope_id": context.get("scope_id"),
                    "quality": context.get("quality"),
                    "agent_plan": context.get("agent_plan"),
                    "tool_observations": context.get("tool_observations"),
                    "decision_brief": context.get("decision_brief"),
                    "trace": context.get("trace"),
                }
                prompt = (
                    "你是跨境电商经营分析师。只能根据以下受控工具结果回答，不得补充未经证据支持的因果。"
                    "不得输出内部ID、UUID、查询名或不存在的广告、库存指标。"
                    "预期收益没有因果或实验依据时必须写明当前数据不足。"
                    "回答正文只解释结构化关键发现、驱动和行动。\n问题：{}\n工具结果：{}"
                ).format(question, json.dumps(model_context, ensure_ascii=False)[:30000])
                try:
                    generated = await self.provider.synthesize(prompt)
                    if generated and generated.strip():
                        validation_error = self._model_answer_error(generated, model_context)
                        if validation_error:
                            run_status = "PARTIAL"
                            self._emit(run_id, "warning", {"message": f"模型输出校验失败，已返回确定性分析：{validation_error}"})
                        else:
                            answer = generated.strip()
                    else:
                        run_status = "PARTIAL"
                        self._emit(run_id, "warning", {"message": "模型输出为空，已返回确定性分析"})
                except Exception as exc:
                    run_status = "PARTIAL"
                    self._emit(run_id, "warning", {"message": f"模型调用失败，已返回确定性分析：{type(exc).__name__}"})
            answer = self._apply_answer_contract(answer, context)
            self._emit(run_id, "stage", {"stage": "生成建议", "status": "completed"})
            self._emit(run_id, "result", {
                "status": run_status,
                "answer": answer,
                "analysis": context,
                "scope_id": bundle.metadata.get("scope_id"),
                "trace": context.get("trace"),
            })
            new_messages = [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
            self.sessions[session_id]["messages"].extend(new_messages)
            if self.state:
                self.state.save_messages(session_id, new_messages)
        except Exception as exc:
            run_status = "FATAL" if isinstance(exc, RuntimeError) else "FAILED"
            self._emit(run_id, "error", {"message": f"分析执行失败：{exc}"})
        finally:
            self.done.add(run_id)
            if self.state:
                self.state.finish_run(run_id, run_status)

    @staticmethod
    def _deterministic_answer(context: dict[str, Any]) -> str:
        brief = context.get("decision_brief", {})
        cases = brief.get("cases", [])
        if brief.get("status") != "SUCCESS" or not cases:
            return "当前数据不足，无法生成该分析。"
        findings = "\n".join(
            f"{index}. {item['finding']['summary']}"
            for index, item in enumerate(cases[:5], 1)
        )
        actions = []
        for item in cases:
            for action in item.get("actions", []):
                actions.append(f"{len(actions) + 1}. {action['title']}：{action['action']}")
                break
        action_text = "\n".join(actions[:5]) or "当前证据不足，无法生成可执行建议。"
        return f"关键发现：\n{findings}\n\n建议动作：\n{action_text}"

    @staticmethod
    def _model_answer_error(answer: str, context: dict[str, Any]) -> str | None:
        text = answer.strip()
        if not text:
            return "输出为空"
        controlled = json.dumps(context, ensure_ascii=False, default=str)
        allowed_numbers = set(re.findall(r"-?\d+(?:\.\d+)?", controlled))
        answer_numbers = re.findall(r"-?\d+(?:\.\d+)?", text)
        unsupported = [
            value for value in answer_numbers
            if value not in allowed_numbers and abs(float(value)) > 10
        ]
        if unsupported:
            return "包含未由受控工具支持的数字 {}".format("、".join(unsupported[:3]))
        return None

    @staticmethod
    def _apply_answer_contract(answer: str, context: dict[str, Any]) -> str:
        dataset = context.get("dataset", {})
        period = context.get("period", {})
        cases = context.get("decision_brief", {}).get("cases", [])
        evidence_labels = _unique_text(
            f"{row.get('metric')}（{row.get('source')}）"
            for item in cases
            for row in item.get("evidence", [])
        )
        limitations = sorted({str(limit) for item in cases for limit in item.get("limitations", []) if limit})
        period_label = f"{period.get('start', '未知')} 至 {period.get('end', '未知')}"
        return (
            f"数据集：{dataset.get('name', '未知')}（{dataset.get('dataset_id', '未知')}）\n"
            f"周期：{period_label}\n"
            f"{answer.strip()}\n\n"
            f"业务证据：{'；'.join(evidence_labels) or '当前数据不足，无法生成该分析。'}\n\n"
            f"限制：{'；'.join(limitations) if limitations else '当前结论仅表示数据贡献关系，不代表真实经营因果。'}"
        )

    async def events(self, run_id: str):
        self._cleanup_expired()
        cursor = 0
        while True:
            events = self.runs.get(run_id)
            if events is None:
                yield {"type": "error", "payload": {"message": "分析运行不存在"}}
                return
            while cursor < len(events):
                yield events[cursor]
                cursor += 1
            if run_id in self.done:
                return
            await asyncio.sleep(0.1)

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Bot,
  Check,
  Circle,
  Download,
  Expand,
  Link2,
  LoaderCircle,
  Mic,
  Paperclip,
  Plus,
  Send,
  Sparkles,
  UserRound,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { TrendChart } from "../components/Charts";
import { MetricCard } from "../components/MetricCard";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Skeleton,
  cx,
} from "../components/ui";
import { api } from "../lib/api";
import { cn } from "../lib/format";
import { useAppState } from "../state/app";
import type {
  AgentRunRequest,
  AgentSessionRequest,
  DecisionBrief,
  DecisionCase,
  OverviewData,
} from "../types";

interface ProviderStatus {
  configured: boolean;
  source: string;
  provider_name: string | null;
  model: string | null;
  wire_api: string | null;
  ccswitch_available: boolean;
  message: string;
}
interface AgentEvent {
  type: "stage" | "tool" | "warning" | "result" | "error";
  payload: Record<string, unknown>;
}
interface AnalysisResult {
  answer: string;
  analysis: {
    question: string;
    dataset: { dataset_id: string; name: string };
    period: { start: string; end: string; type: string };
    tools: string[];
    overview: OverviewData;
    quality: Record<string, unknown>;
    insights: Array<Record<string, unknown>>;
    evidence: Array<Record<string, unknown>>;
    recommendations: Array<Record<string, unknown>>;
    decision_brief: DecisionBrief;
  };
  scope_id: string;
}

const initialAssistant =
  "你好，我是 CrossBorder AI 分析师。你可以询问经营指标、异常原因、证据和行动建议。所有回答都来自受控分析工具。";

const toolLabels: Record<string, string> = {
  get_dataset_profile: "读取数据范围",
  get_data_quality: "校验数据质量",
  query_metrics: "计算注册指标",
  list_anomalies: "识别指标异常",
  get_diagnosis: "拆解驱动因素",
  get_evidence: "构建业务证据",
  get_recommendations: "生成受控行动",
  generate_review_report: "生成经营报告",
};

export function AiAnalystPage() {
  const { datasetId } = useAppState();
  const [sessionId, setSessionId] = useState("");
  const [question, setQuestion] = useState(
    "分析最近一个完整周期中最值得关注的经营问题，并给出证据与建议。",
  );
  const [messages, setMessages] = useState([
    { role: "assistant", content: initialAssistant },
  ]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [running, setRunning] = useState(false);
  const [resultTab, setResultTab] = useState("概览");
  const streamRef = useRef<EventSource | null>(null);
  const status = useQuery({
    queryKey: ["agent-status"],
    queryFn: () => api<ProviderStatus>("/agent/status"),
  });
  const createSession = useMutation({
    mutationFn: () => {
      const payload: AgentSessionRequest = { dataset_id: datasetId };
      return api<{ session_id: string }>("/agent/sessions", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: (response) => setSessionId(response.data.session_id),
  });
  const importConfig = useMutation({
    mutationFn: () =>
      api<ProviderStatus>("/agent/import-ccswitch", {
        method: "POST",
        body: "{}",
      }),
    onSuccess: () => status.refetch(),
  });
  useEffect(() => {
    createSession.mutate();
    return () => streamRef.current?.close();
  }, [datasetId]);
  const submit = async () => {
    if (!question.trim() || !sessionId || running) return;
    const current = question.trim();
    setMessages((items) => [...items, { role: "user", content: current }]);
    setQuestion("");
    setEvents([]);
    setResult(null);
    setRunning(true);
    setResultTab("概览");
    try {
      const payload: AgentRunRequest = {
        question: current,
        dataset_id: datasetId,
      };
      const response = await api<{ run_id: string }>(
        `/agent/sessions/${sessionId}/runs`,
        { method: "POST", body: JSON.stringify(payload) },
      );
      const source = new EventSource(
        `/api/v1/agent/runs/${response.data.run_id}/events`,
      );
      streamRef.current = source;
      source.onmessage = (event) => {
        const item = JSON.parse(event.data) as AgentEvent;
        setEvents((items) => [...items, item]);
        if (item.type === "result") {
          const payload = item.payload as unknown as AnalysisResult;
          setResult(payload);
          setMessages((items) => [
            ...items,
            { role: "assistant", content: payload.answer },
          ]);
          setRunning(false);
          source.close();
        }
        if (item.type === "error") {
          setRunning(false);
          source.close();
        }
      };
      source.onerror = () => {
        setRunning(false);
        source.close();
      };
    } catch (error) {
      setEvents([
        {
          type: "error",
          payload: {
            message: error instanceof Error ? error.message : "分析启动失败",
          },
        },
      ]);
      setRunning(false);
    }
  };
  return (
    <div className="page-enter p-4 md:p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[24px] font-semibold">AI分析师</h1>
          <p className="mt-1 text-sm text-muted">
            让 AI 帮你分析业务、发现问题、提供证据、辅助决策
          </p>
        </div>
        <ProviderPill
          status={status.data?.data}
          loading={status.isLoading}
          importConfig={() => importConfig.mutate()}
          importing={importConfig.isPending}
        />
      </div>
      <div className="grid min-h-[calc(100vh-150px)] grid-cols-1 gap-4 2xl:grid-cols-[420px_minmax(0,1fr)]">
        <Card className="flex min-h-[720px] flex-col overflow-hidden">
          <div className="flex h-14 items-center justify-between border-b border-line px-4">
            <h2 className="text-sm font-semibold">对话</h2>
            <Button
              variant="secondary"
              className="h-8"
              onClick={() => {
                setMessages([{ role: "assistant", content: initialAssistant }]);
                setEvents([]);
                setResult(null);
                createSession.mutate();
              }}
            >
              <Plus size={15} />
              新建分析
            </Button>
          </div>
          <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto p-4">
            {messages.map((message, index) => (
              <ChatMessage key={index} {...message} />
            ))}
            {running && <AnalysisProgress events={events} />}{" "}
            {!running && events.some((item) => item.type === "error") && (
              <ErrorState
                message={cn(
                  events.find((item) => item.type === "error")?.payload.message,
                )}
              />
            )}
          </div>
          <div className="border-t border-line p-3">
            <div className="rounded-panel border border-line bg-white p-3 focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/10">
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit();
                  }
                }}
                rows={3}
                className="w-full resize-none text-sm leading-6 outline-none"
                placeholder="请输入你的问题，支持自然语言提问..."
              />
              <div className="mt-2 flex items-center justify-between">
                <div className="flex gap-1 text-muted">
                  <Button
                    variant="ghost"
                    className="h-8 w-8 p-0"
                    aria-label="语音输入"
                  >
                    <Mic size={16} />
                  </Button>
                  <Button
                    variant="ghost"
                    className="h-8 w-8 p-0"
                    aria-label="附加文件"
                    disabled
                  >
                    <Paperclip size={16} />
                  </Button>
                </div>
                <Button
                  className="h-8 w-8 p-0"
                  disabled={!sessionId || !question.trim() || running}
                  onClick={submit}
                  aria-label="发送问题"
                >
                  {running ? (
                    <LoaderCircle size={16} className="animate-spin" />
                  ) : (
                    <Send size={16} />
                  )}
                </Button>
              </div>
            </div>
            <p className="mt-2 text-right text-[11px] text-[#98a2b3]">
              Shift + Enter 换行，Enter 发送
            </p>
          </div>
        </Card>
        <AnalysisResultPanel
          result={result}
          running={running}
          tab={resultTab}
          setTab={setResultTab}
          datasetId={datasetId}
        />
      </div>
    </div>
  );
}

function ProviderPill({
  status,
  loading,
  importConfig,
  importing,
}: {
  status?: ProviderStatus;
  loading: boolean;
  importConfig: () => void;
  importing: boolean;
}) {
  if (loading) return <Skeleton className="h-9 w-52" />;
  return (
    <div className="flex items-center gap-2">
      <Badge tone={status?.configured ? "green" : "blue"}>
        {status?.configured
          ? `${status.provider_name} · ${status.model}`
          : "演示分析模式"}
      </Badge>
      {status?.ccswitch_available && !status.configured && (
        <Button variant="secondary" onClick={importConfig} disabled={importing}>
          <Link2 size={15} />
          {importing ? "正在导入" : "从 CC Switch 导入"}
        </Button>
      )}
    </div>
  );
}

function ChatMessage({ role, content }: { role: string; content: string }) {
  return (
    <div className={cx("flex gap-3", role === "user" && "flex-row-reverse")}>
      <div
        className={cx(
          "grid h-7 w-7 shrink-0 place-items-center rounded-full",
          role === "user" ? "bg-[#dbe8ff] text-brand" : "bg-brand text-white",
        )}
      >
        {role === "user" ? <UserRound size={15} /> : <Bot size={15} />}
      </div>
      <div
        className={cx(
          "max-w-[88%] rounded-lg px-3 py-2 text-sm leading-6 whitespace-pre-wrap",
          role === "user"
            ? "bg-[#e8f0ff] text-ink"
            : "border border-line bg-white text-[#344054]",
        )}
      >
        {content}
      </div>
    </div>
  );
}

function AnalysisProgress({ events }: { events: AgentEvent[] }) {
  const stages = ["理解问题", "数据分析", "原因分析", "生成建议"];
  const stageMap = new Map(
    events
      .filter((item) => item.type === "stage")
      .map((item) => [String(item.payload.stage), String(item.payload.status)]),
  );
  const tools = events.filter((item) => item.type === "tool");
  return (
    <div className="ml-10 space-y-3 rounded-panel border border-line p-3">
      <p className="text-xs font-semibold">分析进度</p>
      {stages.map((stage) => (
        <div className="flex items-center gap-3 text-xs" key={stage}>
          {stageMap.get(stage) === "completed" ? (
            <Check size={14} className="text-success" />
          ) : stageMap.get(stage) === "running" ? (
            <LoaderCircle size={14} className="animate-spin text-brand" />
          ) : (
            <Circle size={12} className="text-[#d0d5dd]" />
          )}
          <span className={stageMap.has(stage) ? "text-ink" : "text-muted"}>
            {stage}
          </span>
          {stageMap.get(stage) === "running" && (
            <div className="h-1 flex-1 overflow-hidden rounded bg-[#eef2f6]">
              <div className="h-full w-2/3 animate-pulse bg-brand" />
            </div>
          )}
        </div>
      ))}
      {tools.length > 0 && (
        <div className="border-t border-line pt-3">
          <p className="mb-2 flex items-center gap-2 text-xs font-semibold">
            <Wrench size={13} />
            工具执行状态
          </p>
          <div className="space-y-2">
            {tools.map((tool, index) => (
              <div
                key={index}
                className="flex items-center justify-between text-xs text-muted"
              >
                <span>
                  {toolLabels[cn(tool.payload.name)] ?? "执行受控分析工具"}
                </span>
                <Badge tone="green">已完成</Badge>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AnalysisResultPanel({
  result,
  running,
  tab,
  setTab,
  datasetId,
}: {
  result: AnalysisResult | null;
  running: boolean;
  tab: string;
  setTab: (value: string) => void;
  datasetId: string;
}) {
  const tabs = ["概览", "详细分析", "对象排名", "证据明细", "报告预览"];
  const brief = result?.analysis.decision_brief;
  const [selectedCaseId, setSelectedCaseId] = useState("");
  useEffect(() => {
    setSelectedCaseId(brief?.cases[0]?.case_id ?? "");
  }, [result, brief?.period_start]);
  const selectedCase =
    brief?.cases.find((item) => item.case_id === selectedCaseId) ??
    brief?.cases[0];
  if (!result && !running)
    return (
      <Card className="min-h-[720px]">
        <div className="flex h-full min-h-[720px] flex-col items-center justify-center p-8 text-center">
          <div className="grid h-14 w-14 place-items-center rounded-xl bg-[#edf4ff] text-brand">
            <Sparkles size={27} />
          </div>
          <h2 className="mt-5 text-lg font-semibold">开始一次经营分析</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-muted">
            在左侧提出问题。系统会依次调用指标、异常、诊断、证据和建议工具，并在这里生成可复算结果。
          </p>
        </div>
      </Card>
    );
  if (running && !result)
    return (
      <Card className="min-h-[720px] p-5">
        <div className="flex items-center gap-3">
          <LoaderCircle className="animate-spin text-brand" />
          <div>
            <h2 className="font-semibold">正在生成分析结果</h2>
            <p className="mt-1 text-sm text-muted">
              指标与证据完成后将在此处同步刷新
            </p>
          </div>
        </div>
        <div className="mt-8 grid grid-cols-2 gap-4 xl:grid-cols-4">
          {[1, 2, 3, 4].map((item) => (
            <Skeleton className="h-24" key={item} />
          ))}
        </div>
        <Skeleton className="mt-4 h-[310px]" />
        <div className="mt-4 grid grid-cols-3 gap-4">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      </Card>
    );
  return (
    <Card className="min-h-[720px] overflow-hidden">
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b border-line px-4">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">分析结果</h2>
          <Badge tone="green">分析完成</Badge>
        </div>
        <div className="flex gap-2">
          <a href={`/api/v1/reports/${datasetId}/docx`}>
            <Button variant="secondary" className="h-8">
              <Download size={15} />
              导出报告
            </Button>
          </a>
          <Button variant="secondary" className="h-8 w-8 p-0" aria-label="全屏">
            <Expand size={15} />
          </Button>
        </div>
      </div>
      <div className="scrollbar-thin flex gap-6 overflow-x-auto border-b border-line px-4 pt-3">
        {tabs.map((item) => (
          <button
            onClick={() => setTab(item)}
            className={cx(
              "whitespace-nowrap border-b-2 pb-3 text-xs",
              tab === item
                ? "border-brand font-medium text-brand"
                : "border-transparent text-muted",
            )}
            key={item}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="p-4">
        {tab === "概览" && (
          <ResultOverview
            result={result!}
            selectedCase={selectedCase}
            selectedCaseId={selectedCaseId}
            onSelectCase={setSelectedCaseId}
          />
        )}{" "}
        {tab === "详细分析" && <DetailAnalysis result={result!} />}{" "}
        {tab === "对象排名" && (
          <TopImpactPanel
            brief={brief!}
            selectedCaseId={selectedCaseId}
            onSelectCase={setSelectedCaseId}
          />
        )}{" "}
        {tab === "证据明细" && <EvidenceList brief={brief!} />}{" "}
        {tab === "报告预览" && <ReportPreview result={result!} />}
      </div>
    </Card>
  );
}

function ResultOverview({
  result,
  selectedCase,
  selectedCaseId,
  onSelectCase,
}: {
  result: AnalysisResult;
  selectedCase?: DecisionCase;
  selectedCaseId: string;
  onSelectCase: (value: string) => void;
}) {
  const data = result.analysis.overview;
  const brief = result.analysis.decision_brief;
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold">核心指标概览</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {data.kpis.map((metric) => (
            <MetricCard key={metric.label} metric={metric} />
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.65fr)_340px]">
        <TrendChart rows={data.trend} title="GMV 趋势对比" />
        <TopImpactPanel
          brief={brief}
          selectedCaseId={selectedCaseId}
          onSelectCase={onSelectCase}
          compact
        />
      </div>
      {brief.status === "SUCCESS" && selectedCase ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-4">
          <KeyFindingsCard
            brief={brief}
            selectedCaseId={selectedCaseId}
            onSelectCase={onSelectCase}
          />
          <DriversCard item={selectedCase} />
          <EvidenceSummaryCard item={selectedCase} />
          <ActionsCard item={selectedCase} />
        </div>
      ) : (
        <Card className="p-4">
          <p className="text-sm text-muted">
            {brief.message || "当前数据不足，无法生成该分析。"}
          </p>
        </Card>
      )}
      <div className="rounded-md border border-[#b2ccff] bg-[#eff6ff] px-4 py-3 text-xs text-[#175cd3]">
        {brief.unavailable_metrics.map((item) => item.metric).join("、")}
        ：当前数据不足，无法生成对应分析。所有建议仅基于已展示的注册指标与业务证据。
      </div>
    </div>
  );
}

function formatDecisionValue(value: number | null, unit: string) {
  if (value === null || !Number.isFinite(value)) return "—";
  if (/^[A-Z]{3}$/.test(unit)) {
    const fractionDigits = Math.abs(value) < 100 && value !== 0 ? 2 : 0;
    return new Intl.NumberFormat("zh-CN", {
      style: "currency",
      currency: unit,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value);
  }
  if (unit === "ratio") return `${(value * 100).toFixed(1)}%`;
  if (unit === "count") return Math.round(value).toLocaleString("zh-CN");
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatRatio(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

export function TopImpactPanel({
  brief,
  selectedCaseId,
  onSelectCase,
  compact = false,
}: {
  brief: DecisionBrief;
  selectedCaseId: string;
  onSelectCase: (value: string) => void;
  compact?: boolean;
}) {
  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold">异常对象（Top Impact）</h3>
      {brief.top_impact.length ? (
        <div className="mt-3">
          <div className="grid grid-cols-[minmax(0,1fr)_90px_60px_38px] gap-2 border-b border-line pb-2 text-[11px] text-muted">
            <span>对象 / 指标</span>
            <span className="text-right">影响值</span>
            <span className="text-right">占比</span>
            <span className="text-right">等级</span>
          </div>
          <div className="divide-y divide-line">
            {brief.top_impact.map((item) => (
              <button
                key={item.case_id}
                onClick={() => onSelectCase(item.case_id)}
                className={cx(
                  "grid w-full grid-cols-[minmax(0,1fr)_90px_60px_38px] items-center gap-2 py-3 text-left text-xs",
                  selectedCaseId === item.case_id && "bg-[#f8faff]",
                )}
              >
                <span className="min-w-0">
                  <strong className="block truncate font-medium">
                    {item.object_name}
                  </strong>
                  <span className="mt-0.5 block truncate text-muted">
                    {item.object_type} · {item.metric}
                  </span>
                </span>
                <span className="text-right tabular-nums">
                  {formatDecisionValue(item.impact_amount, item.unit)}
                </span>
                <span className="text-right tabular-nums">
                  {formatRatio(item.impact_ratio)}
                </span>
                <Badge
                  tone={
                    item.priority === "P0"
                      ? "red"
                      : item.priority === "P1"
                        ? "orange"
                        : "neutral"
                  }
                  className="justify-center px-1"
                >
                  {item.priority}
                </Badge>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted">
          {brief.message || "当前数据不足，无法生成该分析。"}
        </p>
      )}
      {!compact && brief.top_impact.length > 0 && (
        <p className="mt-3 text-xs text-muted">
          点击对象可查看同一分析链中的驱动、证据和行动。
        </p>
      )}
    </Card>
  );
}

export function KeyFindingsCard({
  brief,
  selectedCaseId,
  onSelectCase,
}: {
  brief: DecisionBrief;
  selectedCaseId: string;
  onSelectCase: (value: string) => void;
}) {
  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold">关键发现</h3>
      <div className="mt-3 space-y-3">
        {brief.cases.map((item) => (
          <button
            key={item.case_id}
            onClick={() => onSelectCase(item.case_id)}
            className={cx(
              "flex w-full items-start gap-2 text-left text-xs leading-5 text-muted",
              selectedCaseId === item.case_id && "text-ink",
            )}
          >
            <span className="mt-1 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-[#edf4ff] text-[10px] text-brand">
              {item.rank}
            </span>
            <span>
              <strong className="block font-medium text-ink">
                {item.finding.what_happened}
              </strong>
              <span className="block">
                影响程度 {item.finding.impact_level} · 主要对象{" "}
                {item.finding.main_object}
              </span>
              <span className="block">{item.finding.summary}</span>
            </span>
          </button>
        ))}
      </div>
    </Card>
  );
}

export function DriversCard({ item }: { item: DecisionCase }) {
  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold">驱动因素</h3>
      <div className="mt-3 space-y-4">
        {item.drivers.length ? (
          item.drivers.map((driver) => (
            <div key={`${driver.rank}-${driver.driver_code}`}>
              <div className="flex items-start justify-between gap-2 text-xs">
                <span>
                  {driver.rank}. {driver.name}
                </span>
                <span className="text-right tabular-nums text-muted">
                  {formatDecisionValue(driver.impact_amount, driver.unit)}
                  <br />
                  贡献{" "}
                  {driver.contribution_share === null
                    ? "—"
                    : `${(driver.contribution_share * 100).toFixed(1)}%`}
                </span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded bg-[#eef2f6]">
                <div
                  className="h-full rounded bg-brand"
                  style={{
                    width: `${Math.min(100, Math.max(0, (driver.contribution_share ?? 0) * 100))}%`,
                  }}
                />
              </div>
            </div>
          ))
        ) : (
          <p className="text-xs leading-5 text-muted">
            当前数据不足，无法生成该分析。
          </p>
        )}
      </div>
    </Card>
  );
}

export function EvidenceSummaryCard({ item }: { item: DecisionCase }) {
  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold">数据证据</h3>
      <div className="mt-3 space-y-4">
        {item.evidence.map((row) => (
          <div key={`${row.metric_id}-${row.period_start}`} className="text-xs">
            <div className="flex items-center justify-between gap-2">
              <strong className="font-medium">{row.metric}</strong>
              <Badge tone="green">可复算</Badge>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-muted">
              <span>
                当前值
                <strong className="mt-0.5 block font-medium text-ink">
                  {formatDecisionValue(row.current_value, row.unit)}
                </strong>
              </span>
              <span>
                对比值
                <strong className="mt-0.5 block font-medium text-ink">
                  {formatDecisionValue(row.comparison_value, row.unit)}
                </strong>
              </span>
            </div>
            <p className="mt-2 text-muted">
              变化：{formatRatio(row.change_rate)}
            </p>
            <p className="mt-1 text-muted">来源：{row.source}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function ActionsCard({ item }: { item: DecisionCase }) {
  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold">建议动作</h3>
      <div className="mt-3 space-y-4">
        {item.actions.length ? (
          item.actions.map((action, index) => (
            <div key={`${action.title}-${index}`} className="text-xs leading-5">
              <div className="flex items-start gap-2">
                <Badge tone={action.priority === "P0" ? "red" : "orange"}>
                  {action.priority}
                </Badge>
                <strong className="font-medium">{action.title}</strong>
              </div>
              <p className="mt-2 text-[#475467]">{action.action}</p>
              <p className="mt-2 text-muted">原因：{action.reason}</p>
              <p className="mt-1 text-muted">
                影响对象：{action.affected_object}
              </p>
              <p className="mt-1 text-muted">
                预期收益：{action.expected_benefit.message}
              </p>
            </div>
          ))
        ) : (
          <p className="text-xs leading-5 text-muted">
            当前数据不足，无法生成该分析。
          </p>
        )}
      </div>
    </Card>
  );
}

function DetailAnalysis({ result }: { result: AnalysisResult }) {
  const brief = result.analysis.decision_brief;
  if (brief.status !== "SUCCESS" || !brief.cases.length) {
    return <p className="text-sm text-muted">当前数据不足，无法生成该分析。</p>;
  }
  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="text-xl font-semibold">经营问题分析</h2>
      <div className="mt-5 space-y-5">
        {brief.cases.map((item) => (
          <Card className="p-5 shadow-none" key={item.case_id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs text-muted">第 {item.rank} 位影响</p>
                <h3 className="mt-1 font-semibold">
                  {item.finding.what_happened}
                </h3>
              </div>
              <Badge
                tone={
                  item.anomaly.priority === "P0"
                    ? "red"
                    : item.anomaly.priority === "P1"
                      ? "orange"
                      : "neutral"
                }
              >
                {item.anomaly.priority}
              </Badge>
            </div>
            <p className="mt-3 text-sm leading-6 text-[#475467]">
              {item.finding.summary}
            </p>
            <div className="mt-4 rounded-md bg-[#f8fafc] p-3 text-xs leading-6 text-muted">
              <p>指标异常：{item.chain.anomaly}</p>
              <p>
                ↓ 驱动因素：{item.chain.drivers.join("、") || "当前数据不足"}
              </p>
              <p>↓ 影响对象：{item.chain.object}</p>
              <p>
                ↓ 业务证据：{item.chain.evidence.join("、") || "当前数据不足"}
              </p>
              <p>
                ↓ 最终建议：
                {item.chain.actions.join("、") ||
                  "当前数据不足，无法生成该分析。"}
              </p>
            </div>
            {item.actions.map((action, index) => (
              <div className="mt-5" key={`${action.title}-${index}`}>
                <h4 className="text-sm font-semibold">{action.title}</h4>
                <p className="mt-2 text-sm leading-6 text-[#475467]">
                  {action.action}
                </p>
                <ol className="mt-3 space-y-2 text-sm text-[#475467]">
                  {action.steps.map((step, stepIndex) => (
                    <li className="flex gap-2" key={step}>
                      <span className="text-brand">{stepIndex + 1}.</span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
                <div className="mt-3 grid gap-2 text-xs text-muted sm:grid-cols-2">
                  <span>负责人：{action.owner_role}</span>
                  <span>目标指标：{action.expected_metric}</span>
                  <span>验证周期：{action.validation_period}</span>
                  <span>保护指标：{action.guardrail_metrics.join("、")}</span>
                </div>
                <p className="mt-2 text-xs text-muted">
                  预期收益：{action.expected_benefit.message}
                </p>
                <p className="mt-1 text-xs text-muted">
                  停止条件：{action.stop_condition}
                </p>
              </div>
            ))}
          </Card>
        ))}
      </div>
    </div>
  );
}
function EvidenceList({ brief }: { brief: DecisionBrief }) {
  const rows = brief.cases.flatMap((item) =>
    item.evidence.map((evidence) => ({
      ...evidence,
      objectName: item.anomaly.object_name,
    })),
  );
  return (
    <div className="space-y-3">
      {rows.length ? (
        rows.map((item, index) => (
          <Card
            className="p-4 shadow-none"
            key={`${item.objectName}-${item.metric_id}-${item.period_start}-${index}`}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">{item.metric}</p>
                <p className="mt-1 text-xs text-muted">
                  影响对象：{item.objectName}
                </p>
              </div>
              <Badge tone="green">可复算</Badge>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-muted md:grid-cols-4">
              <span>
                当前值：{formatDecisionValue(item.current_value, item.unit)}
              </span>
              <span>
                对比值：{formatDecisionValue(item.comparison_value, item.unit)}
              </span>
              <span>变化：{formatRatio(item.change_rate)}</span>
              <span>来源：{item.source}</span>
            </div>
            <p className="mt-3 text-xs leading-5 text-muted">
              指标口径：{item.formula}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted">
              当前周期：{item.period_start} 至 {item.period_end}
              {item.comparison_start && item.comparison_end
                ? ` · 对比周期：${item.comparison_start} 至 ${item.comparison_end}`
                : ""}
            </p>
          </Card>
        ))
      ) : (
        <p className="text-sm text-muted">当前数据不足，无法生成该分析。</p>
      )}
    </div>
  );
}
function ReportPreview({ result }: { result: AnalysisResult }) {
  const brief = result.analysis.decision_brief;
  return (
    <article className="mx-auto max-w-3xl py-4">
      <div className="border-b border-line pb-8">
        <p className="text-xs font-medium text-brand">
          CROSSBORDER BUSINESS REVIEW
        </p>
        <h1 className="mt-3 text-3xl font-semibold">跨境电商经营分析报告</h1>
        <p className="mt-3 text-sm text-muted">
          数据集：{result.analysis.dataset.name} · 周期：
          {result.analysis.period.start} 至 {result.analysis.period.end}
        </p>
      </div>
      <section className="py-7">
        <h2 className="text-lg font-semibold">执行摘要</h2>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-[#475467]">
          {result.answer}
        </p>
      </section>
      <section className="border-t border-line py-7">
        <h2 className="text-lg font-semibold">关键发现与行动</h2>
        <div className="mt-4 space-y-4">
          {brief.cases.map((item) => (
            <div className="flex gap-4" key={item.case_id}>
              <span className="font-semibold text-brand">
                {String(item.rank).padStart(2, "0")}
              </span>
              <div>
                <p className="text-sm font-medium">{item.finding.summary}</p>
                {item.actions.map((action, index) => (
                  <div className="mt-2" key={`${action.title}-${index}`}>
                    <p className="text-sm text-[#475467]">
                      {action.title}：{action.action}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-muted">
                      验证周期：{action.validation_period} · 停止条件：
                      {action.stop_condition}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-muted">
                      预期收益：{action.expected_benefit.message}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="border-t border-line py-7">
        <h2 className="text-lg font-semibold">证据索引</h2>
        <div className="mt-3 space-y-2 text-sm leading-7 text-muted">
          {brief.cases.flatMap((item) =>
            item.evidence.map((evidence) => (
              <p key={`${item.case_id}-${evidence.metric_id}`}>
                {item.anomaly.object_name} · {evidence.metric}：当前值{" "}
                {formatDecisionValue(evidence.current_value, evidence.unit)}，
                对比值{" "}
                {formatDecisionValue(evidence.comparison_value, evidence.unit)}
                ，变化 {formatRatio(evidence.change_rate)}，来源{" "}
                {evidence.source}
              </p>
            )),
          )}
          {!brief.cases.length && <p>当前数据不足，无法生成该分析。</p>}
        </div>
      </section>
    </article>
  );
}

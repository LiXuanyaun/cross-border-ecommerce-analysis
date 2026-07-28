import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  CircleGauge,
  Database,
  FileClock,
  FileSpreadsheet,
  FileUp,
  Import,
  Loader2,
  Search,
  Settings2,
  TableProperties,
  XCircle,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { api, apiForm } from "../lib/api";
import { cn } from "../lib/format";
import type { DatasetSummary } from "../types";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton, cx } from "../components/ui";
import { useAppState } from "../state/app";

const dataNav = [
  { label: "数据集", icon: Database },
  { label: "导入记录", icon: Import },
  { label: "数据质量", icon: CircleGauge },
  { label: "字段管理", icon: TableProperties },
  { label: "指标目录", icon: BookOpen },
  { label: "规则目录", icon: AlertTriangle },
  { label: "查询记录", icon: FileClock },
  { label: "汇率配置", icon: Settings2 },
  { label: "容量治理", icon: Database },
];

interface DetailData {
  dataset: DatasetSummary;
  quality: Record<string, unknown>;
  quality_dimensions: Array<Record<string, unknown>>;
  fields: Array<Record<string, unknown>>;
  capabilities: Array<Record<string, unknown>>;
  query_runs: Array<Record<string, unknown>>;
  lineage: Record<string, unknown>;
  import_history: Array<Record<string, unknown>>;
  metric_catalog: Array<Record<string, unknown>>;
  rule_catalog: Array<Record<string, unknown>>;
  capacity?: {
    database_bytes: number;
    file_bytes: Record<string, number>;
    scope_statuses: Record<string, number>;
    record_counts: Record<string, number>;
    cleanup_recommendations: string[];
    retention_policy: Record<string, number>;
  };
  fx_lineage?: Record<string, unknown>;
}

interface ImportIssue {
  severity: "FATAL" | "WARNING" | string;
  code: string;
  message: string;
  field?: string | null;
  row_count?: number;
  details?: Record<string, unknown>;
}

interface ImportFieldMapping {
  standard_field: string;
  source_field: string | null;
  dtype: string;
  required: boolean;
  confidence: number;
  requires_confirmation: boolean;
  status: string;
  sample_values: unknown[];
}

interface ImportFilePreview {
  filename: string;
  source_file_id: string;
  status: string;
  metadata: {
    rows: number;
    columns: number;
    file_size: number;
    encoding: string | null;
  };
  sheets: string[];
  selected_sheet: string | null;
  columns: string[];
  field_mappings: ImportFieldMapping[];
  issues: ImportIssue[];
  capabilities: Array<{ id: string; name: string; status: string; reason: string }>;
}

interface ImportPreview {
  status: string;
  file_count: number;
  total_rows: number;
  files: ImportFilePreview[];
  batch_issues: ImportIssue[];
  next_step: string;
}

interface ImportConfiguration {
  datasetName: string;
  selectedSheets: Record<string, string>;
  mapping: Record<string, string>;
  dataGrain: "order" | "order_item";
  amountSemantic: "order_total" | "line_amount";
  sourceCurrency: string;
  targetCurrency: string;
}

interface ImportCommitResult {
  status: "READY" | "BLOCKED" | string;
  dataset_id: string | null;
  source_file_id: string;
  source_file_ids: string[];
  reused: boolean;
  row_count: number;
  issues: ImportIssue[];
}

export function DataHubPage() {
  const { datasetId, setDatasetId } = useAppState();
  const queryClient = useQueryClient();
  const [activeNav, setActiveNav] = useState("数据集");
  const [search, setSearch] = useState("");
  const [detailTab, setDetailTab] = useState("概况");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [committing, setCommitting] = useState(false);
  const [commitError, setCommitError] = useState("");
  const [commitResult, setCommitResult] = useState<ImportCommitResult | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [archiveError, setArchiveError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const datasets = useQuery({ queryKey: ["datasets"], queryFn: () => api<DatasetSummary[]>("/datasets") });
  const detail = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api<DetailData>(`/datasets/${datasetId}`),
    enabled: !!datasetId,
  });
  const filtered = useMemo(
    () => (datasets.data?.data ?? []).filter(item => `${item.name}${item.description}`.toLowerCase().includes(search.toLowerCase())),
    [datasets.data, search],
  );

  async function previewFiles(files: File[], selectedSheets: Record<string, string> = {}) {
    if (!files.length) return;
    const form = new FormData();
    files.forEach(file => form.append("files", file));
    if (Object.keys(selectedSheets).length) form.append("selected_sheets_json", JSON.stringify(selectedSheets));
    setUploading(true);
    setUploadError("");
    try {
      const response = await apiForm<ImportPreview>("/imports/preview", form);
      setPreview(response.data);
      setActiveNav("导入记录");
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "导入预检失败");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return;
    const nextFiles = Array.from(files);
    setSelectedFiles(nextFiles);
    setCommitResult(null);
    setCommitError("");
    await previewFiles(nextFiles);
  }

  async function handleSheetChange(filename: string, sheet: string) {
    setCommitResult(null);
    const selectedSheets = Object.fromEntries(
      (preview?.files ?? []).filter(item => item.selected_sheet).map(item => [item.filename, item.selected_sheet as string]),
    );
    selectedSheets[filename] = sheet;
    await previewFiles(selectedFiles, selectedSheets);
  }

  async function handleCommit(configuration: ImportConfiguration) {
    if (!selectedFiles.length) return;
    const form = new FormData();
    selectedFiles.forEach(file => form.append("files", file));
    form.append("mapping_json", JSON.stringify(configuration.mapping));
    form.append("dataset_name", configuration.datasetName);
    form.append("selected_sheets_json", JSON.stringify(configuration.selectedSheets));
    form.append("data_grain", configuration.dataGrain);
    form.append("amount_semantic", configuration.amountSemantic);
    form.append("source_currency", configuration.sourceCurrency);
    form.append("target_currency", configuration.targetCurrency);
    setCommitting(true);
    setCommitError("");
    try {
      const response = await apiForm<ImportCommitResult>("/imports", form);
      setCommitResult(response.data);
      if (response.data.status === "READY" && response.data.dataset_id) {
        await queryClient.invalidateQueries({ queryKey: ["datasets"] });
        setDatasetId(response.data.dataset_id);
        await queryClient.invalidateQueries({ queryKey: ["dataset", response.data.dataset_id] });
      }
    } catch (error) {
      setCommitError(error instanceof Error ? error.message : "正式导入失败");
    } finally {
      setCommitting(false);
    }
  }

  async function handleArchiveDataset() {
    if (!datasetId) return;
    setArchiving(true);
    setArchiveError("");
    try {
      await api(`/datasets/${datasetId}/archive`, { method: "POST" });
      await queryClient.invalidateQueries({ queryKey: ["datasets"] });
      await queryClient.invalidateQueries({ queryKey: ["dataset", datasetId] });
      setDatasetId("demo-all");
      setDetailTab("概况");
    } catch (error) {
      setArchiveError(error instanceof Error ? error.message : "归档数据集失败");
    } finally {
      setArchiving(false);
    }
  }

  return (
    <div className="page-enter p-4 md:p-6">
      <h1 className="mb-4 text-[24px] font-semibold">数据中心</h1>
      <div className="grid min-h-[calc(100vh-128px)] grid-cols-1 gap-4 xl:grid-cols-[142px_minmax(0,1fr)_430px]">
        <Card className="h-fit p-3">
          <div className="space-y-1">
            {dataNav.map(item => (
              <button
                key={item.label}
                onClick={() => setActiveNav(item.label)}
                className={cx(
                  "flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm text-[#475467] hover:bg-[#f5f7fa]",
                  activeNav === item.label && "border border-brand/40 bg-[#f3f6ff] text-brand",
                )}
              >
                <item.icon size={17} />
                {item.label}
              </button>
            ))}
          </div>
        </Card>

        <Card className="min-w-0 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
            <div>
              <h2 className="font-semibold">{activeNav === "数据集" ? "数据集列表" : activeNav}</h2>
              <p className="mt-1 text-xs text-muted">
                {activeNav === "导入记录" ? "先预检并确认数据合同，通过后再原子入库" : "数据集可追溯到源文件及明确的数据合同"}
              </p>
            </div>
            <div className="flex gap-2">
              <label className="flex h-9 items-center gap-2 rounded-md border border-line px-3 text-muted">
                <Search size={15} />
                <input
                  value={search}
                  onChange={event => setSearch(event.target.value)}
                  placeholder="搜索数据集..."
                  className="w-40 bg-transparent text-sm text-ink outline-none"
                />
              </label>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept=".csv,.txt,.xlsx,.xls"
                className="hidden"
                onChange={event => handleFiles(event.target.files)}
              />
              <Button onClick={() => inputRef.current?.click()} disabled={uploading}>
                {uploading ? <Loader2 size={16} className="animate-spin" /> : <FileUp size={16} />}
                导入数据集
              </Button>
            </div>
          </div>
          {uploadError && <div className="p-4"><ErrorState message={uploadError} /></div>}
          {datasets.isLoading ? (
            <div className="space-y-3 p-4">{[1, 2, 3].map(item => <Skeleton className="h-24" key={item} />)}</div>
          ) : datasets.isError ? (
            <div className="p-4"><ErrorState message={datasets.error.message} /></div>
          ) : activeNav === "导入记录" ? (
            <ImportPreviewPanel
              preview={preview}
              sourceFileCount={selectedFiles.length}
              uploading={uploading}
              committing={committing}
              commitError={commitError}
              commitResult={commitResult}
              onSheetChange={handleSheetChange}
              onCommit={handleCommit}
            />
          ) : activeNav !== "数据集" ? (
            <SectionPreview nav={activeNav} detail={detail.data?.data} />
          ) : filtered.length ? (
            <DatasetList items={filtered} datasetId={datasetId} select={(id) => { setDatasetId(id); setDetailTab("概况"); }} />
          ) : (
            <EmptyState title="没有匹配的数据集" description="调整搜索条件后重试。" />
          )}
        </Card>

        <aside>
          {detail.isLoading ? (
            <Skeleton className="h-[700px]" />
          ) : detail.data ? (
            <DatasetDetail
              data={detail.data.data}
              tab={detailTab}
              setTab={setDetailTab}
              archiving={archiving}
              archiveError={archiveError}
              onArchive={handleArchiveDataset}
            />
          ) : (
            <Card><EmptyState title="选择一个数据集" description="右侧将显示质量、字段、能力和查询记录。" /></Card>
          )}
        </aside>
      </div>
    </div>
  );
}

function DatasetList({ items, datasetId, select }: { items: DatasetSummary[]; datasetId: string; select: (id: string) => void }) {
  return (
    <div className="divide-y divide-line">
      {items.map(item => (
        <button
          onClick={() => select(item.dataset_id)}
          key={item.dataset_id}
          className={cx(
            "grid w-full gap-3 p-4 text-left transition hover:bg-[#f8faff] md:grid-cols-[minmax(220px,1.4fr)_120px_140px_90px_26px] md:items-center",
            item.dataset_id === datasetId && "bg-[#f5f8ff] ring-1 ring-inset ring-brand/40",
          )}
        >
          <div>
            <div className="flex items-center gap-2">
              <FileSpreadsheet size={17} className="text-brand" />
              <span className="font-medium">{item.name}</span>
              {item.is_demo && <Badge tone="blue">演示</Badge>}
            </div>
            <p className="mt-1 line-clamp-1 pl-6 text-xs text-muted">{item.description}</p>
          </div>
          <div><p className="text-xs text-muted">数据量</p><p className="mt-1 text-sm tabular-nums">{item.row_count.toLocaleString()} 行</p></div>
          <div><p className="text-xs text-muted">时间范围</p><p className="mt-1 text-xs">{item.period_start}<br />{item.period_end}</p></div>
          <div><p className="text-xs text-muted">质量评分</p><p className="mt-1 font-semibold text-success">{item.quality_score}</p></div>
          <ChevronRight size={17} className="text-muted" />
        </button>
      ))}
    </div>
  );
}

function ImportPreviewPanel({
  preview,
  sourceFileCount,
  uploading,
  committing,
  commitError,
  commitResult,
  onSheetChange,
  onCommit,
}: {
  preview: ImportPreview | null;
  sourceFileCount: number;
  uploading: boolean;
  committing: boolean;
  commitError: string;
  commitResult: ImportCommitResult | null;
  onSheetChange: (filename: string, sheet: string) => Promise<void>;
  onCommit: (configuration: ImportConfiguration) => Promise<void>;
}) {
  if (!preview) {
    return <EmptyState title="暂无导入记录" description="选择 CSV 或 XLSX 后将显示字段映射和质量预检。" />;
  }
  const blocked = preview.status === "BLOCKED";
  return (
    <div className="space-y-4 p-4">
      {commitError && <ErrorState message={commitError} />}
      {commitResult && (
        <div className={cx(
          "rounded-md border p-4",
          commitResult.status === "READY" ? "border-success/30 bg-[#f6fef9]" : "border-danger/30 bg-[#fff7f6]",
        )}>
          <div className="flex items-start gap-3">
            {commitResult.status === "READY"
              ? <CheckCircle2 size={20} className="mt-0.5 text-success" />
              : <XCircle size={20} className="mt-0.5 text-danger" />}
            <div>
              <p className="font-medium">
                {commitResult.status === "READY"
                  ? (commitResult.reused ? "已复用现有数据集" : "数据集已正式入库")
                  : "正式导入被阻断"}
              </p>
              <p className="mt-1 break-all text-xs text-muted">
                {commitResult.dataset_id
                  ? `${commitResult.dataset_id} · ${commitResult.row_count.toLocaleString()} 行`
                  : "请按阻断原因修正配置或源文件"}
              </p>
            </div>
          </div>
          {commitResult.issues.length > 0 && <IssueList issues={commitResult.issues} title="导入结果" compact />}
        </div>
      )}
      <div className={cx("rounded-md border p-4", blocked ? "border-danger/30 bg-[#fff7f6]" : "border-success/30 bg-[#f6fef9]")}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            {blocked ? <XCircle size={20} className="text-danger" /> : <CheckCircle2 size={20} className="text-success" />}
            <div>
              <p className="font-medium">{blocked ? "预检阻断" : "预检通过"}</p>
              <p className="mt-1 text-xs text-muted">{preview.file_count} 个文件，{preview.total_rows.toLocaleString()} 行 · {preview.next_step}</p>
            </div>
          </div>
          <Badge tone={blocked ? "red" : "green"}>{preview.status}</Badge>
        </div>
      </div>

      {preview.batch_issues.length > 0 && <IssueList issues={preview.batch_issues} title="批次问题" />}

      <div className="divide-y divide-line rounded-md border border-line">
        {preview.files.map(file => (
          <div key={file.source_file_id} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <FileSpreadsheet size={17} className="text-brand" />
                  <p className="font-medium">{file.filename}</p>
                  <Badge tone={file.status === "BLOCKED" || file.status === "FAILED" ? "red" : "green"}>{file.status}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted">
                  {Number(file.metadata.rows ?? 0).toLocaleString()} 行 · {file.metadata.columns} 列
                  {file.metadata.encoding ? ` · ${file.metadata.encoding}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {file.sheets.length > 0 && (
                  <select
                    aria-label={`${file.filename} Sheet`}
                    value={file.selected_sheet ?? ""}
                    disabled={uploading}
                    onChange={event => onSheetChange(file.filename, event.target.value)}
                    className="h-8 rounded-md border border-line bg-white px-2 text-xs outline-none focus:border-brand"
                  >
                    {file.sheets.map(sheet => <option key={sheet} value={sheet}>{sheet}</option>)}
                  </select>
                )}
                <p className="text-xs text-muted">{file.source_file_id}</p>
              </div>
            </div>
            {file.issues.length > 0 && <IssueList issues={file.issues} title="文件问题" compact />}
            <MappingTable rows={file.field_mappings} />
            <div className="mt-3 flex flex-wrap gap-2">
              {file.capabilities.map(item => (
                <Badge key={item.id} tone={item.status === "FULL" ? "green" : "neutral"}>{item.name}</Badge>
              ))}
            </div>
          </div>
        ))}
      </div>
      {!blocked && preview.files.length === sourceFileCount && sourceFileCount > 0 && (
        <ImportConfirmationForm
          key={preview.files.map(item => `${item.source_file_id}-${item.selected_sheet ?? "csv"}`).join("|")}
          files={preview.files}
          committing={committing}
          onCommit={onCommit}
        />
      )}
    </div>
  );
}

function ImportConfirmationForm({
  files,
  committing,
  onCommit,
}: {
  files: ImportFilePreview[];
  committing: boolean;
  onCommit: (configuration: ImportConfiguration) => Promise<void>;
}) {
  const file = files[0];
  const [datasetName, setDatasetName] = useState(file.filename.replace(/\.[^.]+$/, ""));
  const [mapping, setMapping] = useState<Record<string, string>>(() => Object.fromEntries(
    file.field_mappings.filter(item => item.source_field).map(item => [item.standard_field, item.source_field as string]),
  ));
  const [dataGrain, setDataGrain] = useState<"order" | "order_item">("order");
  const [amountSemantic, setAmountSemantic] = useState<"order_total" | "line_amount">("order_total");
  const [sourceCurrency, setSourceCurrency] = useState("CNY");
  const [targetCurrency, setTargetCurrency] = useState("CNY");
  const requiredMapped = file.field_mappings
    .filter(item => item.required)
    .every(item => Boolean(mapping[item.standard_field]));
  const supportedContract = dataGrain === "order_item" || amountSemantic === "order_total";
  const currenciesValid = /^[A-Za-z]{3}$/.test(sourceCurrency) && /^[A-Za-z]{3}$/.test(targetCurrency);
  const canSubmit = datasetName.trim() && requiredMapped && supportedContract && currenciesValid && !committing;

  return (
    <form
      className="space-y-4 rounded-md border border-line p-4"
      onSubmit={event => {
        event.preventDefault();
        if (!canSubmit) return;
        onCommit({
          datasetName,
          selectedSheets: Object.fromEntries(
            files.filter(item => item.selected_sheet).map(item => [item.filename, item.selected_sheet as string]),
          ),
          mapping,
          dataGrain,
          amountSemantic,
          sourceCurrency: sourceCurrency.toUpperCase(),
          targetCurrency: targetCurrency.toUpperCase(),
        });
      }}
    >
      <div>
        <h3 className="font-semibold">确认导入合同</h3>
        <p className="mt-1 text-xs text-muted">{files.length} 个文件将作为一个数据集原子提交，并保存逐行来源血缘。</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <FormField label="数据集名称">
          <input value={datasetName} onChange={event => setDatasetName(event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand" />
        </FormField>
        <FormField label="数据粒度">
          <select value={dataGrain} onChange={event => setDataGrain(event.target.value as "order" | "order_item")} className="h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand">
            <option value="order">订单粒度</option>
            <option value="order_item">订单商品粒度</option>
          </select>
        </FormField>
        <FormField label="金额语义">
          <select value={amountSemantic} onChange={event => setAmountSemantic(event.target.value as "order_total" | "line_amount")} className="h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand">
            <option value="order_total">订单总金额</option>
            <option value="line_amount">商品行金额</option>
          </select>
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="源币种">
            <input value={sourceCurrency} maxLength={3} onChange={event => setSourceCurrency(event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-3 text-sm uppercase text-ink outline-none focus:border-brand" />
          </FormField>
          <FormField label="目标币种">
            <input value={targetCurrency} maxLength={3} onChange={event => setTargetCurrency(event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-3 text-sm uppercase text-ink outline-none focus:border-brand" />
          </FormField>
        </div>
      </div>
      <EditableMappingTable file={file} mapping={mapping} setMapping={setMapping} />
      <div className="flex justify-end">
        <Button type="submit" disabled={!canSubmit}>
          {committing ? <Loader2 size={16} className="animate-spin" /> : <Database size={16} />}
          确认并入库
        </Button>
      </div>
    </form>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-xs text-muted"><span className="mb-1.5 block">{label}</span>{children}</label>;
}

function EditableMappingTable({
  file,
  mapping,
  setMapping,
}: {
  file: ImportFilePreview;
  mapping: Record<string, string>;
  setMapping: (mapping: Record<string, string>) => void;
}) {
  const visible = file.field_mappings.filter(row => row.required || row.source_field).slice(0, 12);
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="min-w-full text-left text-xs">
        <thead className="bg-[#f8fafc] text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">标准字段</th>
            <th className="px-3 py-2 font-medium">源字段确认</th>
            <th className="px-3 py-2 font-medium">置信度</th>
            <th className="px-3 py-2 font-medium">样例</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {visible.map(row => (
            <tr key={row.standard_field}>
              <td className="px-3 py-2 font-medium">{row.standard_field}{row.required && <span className="ml-1 text-danger">*</span>}</td>
              <td className="px-3 py-2">
                <select
                  value={mapping[row.standard_field] ?? ""}
                  onChange={event => setMapping({ ...mapping, [row.standard_field]: event.target.value })}
                  className="h-8 min-w-36 rounded-md border border-line bg-white px-2 outline-none focus:border-brand"
                >
                  <option value="">未映射</option>
                  {file.columns.map(column => <option key={column} value={column}>{column}</option>)}
                </select>
              </td>
              <td className="px-3 py-2">{Math.round(row.confidence * 100)}%</td>
              <td className="max-w-[220px] truncate px-3 py-2 text-muted">{row.sample_values.map(value => cn(value)).join(" / ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IssueList({ issues, title, compact }: { issues: ImportIssue[]; title: string; compact?: boolean }) {
  return (
    <div className={cx("rounded-md border border-line bg-white", compact ? "mt-3 p-3" : "p-4")}>
      <p className="flex items-center gap-2 text-sm font-medium"><AlertTriangle size={16} className="text-warning" />{title}</p>
      <div className="mt-2 space-y-2">
        {issues.map((issue, index) => (
          <div key={`${issue.code}-${index}`} className="flex items-start justify-between gap-3 text-xs">
            <div>
              <p className="font-medium">{issue.message}</p>
              <p className="mt-1 text-muted">{issue.code}{issue.field ? ` · ${issue.field}` : ""}{issue.row_count ? ` · ${issue.row_count} 行` : ""}</p>
            </div>
            <Badge tone={issue.severity === "FATAL" ? "red" : "orange"}>{issue.severity}</Badge>
          </div>
        ))}
      </div>
    </div>
  );
}

function MappingTable({ rows }: { rows: ImportFieldMapping[] }) {
  const visible = rows.filter(row => row.required || row.source_field).slice(0, 12);
  return (
    <div className="mt-3 overflow-x-auto rounded-md border border-line">
      <table className="min-w-full text-left text-xs">
        <thead className="bg-[#f8fafc] text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">标准字段</th>
            <th className="px-3 py-2 font-medium">原字段</th>
            <th className="px-3 py-2 font-medium">类型</th>
            <th className="px-3 py-2 font-medium">置信度</th>
            <th className="px-3 py-2 font-medium">样例</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {visible.map(row => (
            <tr key={row.standard_field}>
              <td className="px-3 py-2 font-medium">{row.standard_field}{row.required && <span className="ml-1 text-danger">*</span>}</td>
              <td className="px-3 py-2">{row.source_field ?? "未识别"}</td>
              <td className="px-3 py-2 text-muted">{row.dtype}</td>
              <td className="px-3 py-2">{Math.round(row.confidence * 100)}%</td>
              <td className="max-w-[220px] truncate px-3 py-2 text-muted">{row.sample_values.map(value => cn(value)).join(" / ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DatasetDetail({
  data,
  tab,
  setTab,
  archiving,
  archiveError,
  onArchive,
}: {
  data: DetailData;
  tab: string;
  setTab: (value: string) => void;
  archiving: boolean;
  archiveError: string;
  onArchive: () => Promise<void>;
}) {
  const tabs = ["概况", "字段信息", "质量问题", "支持能力", "查询记录"];
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-line p-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-md bg-[#edf4ff] text-brand"><Database size={17} /></span>
              <h2 className="font-semibold">{data.dataset.name}</h2>
              <Badge tone="green">正常</Badge>
            </div>
            <p className="mt-2 text-xs leading-5 text-muted">{data.dataset.description}</p>
          </div>
          {!data.dataset.is_demo && (
            <Button variant="secondary" className="h-8" disabled={archiving} onClick={onArchive}>
              {archiving ? <Loader2 size={15} className="animate-spin" /> : <FileClock size={15} />}
              归档
            </Button>
          )}
        </div>
        {archiveError && <div className="mt-3"><ErrorState message={archiveError} /></div>}
        <div className="scrollbar-thin mt-4 flex gap-5 overflow-x-auto">
          {tabs.map(item => (
            <button
              key={item}
              onClick={() => setTab(item)}
              className={cx("whitespace-nowrap border-b-2 pb-2 text-xs text-muted", item === tab ? "border-brand font-medium text-brand" : "border-transparent")}
            >
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="p-4">
        {tab === "概况" && <OverviewDetail data={data} />}
        {tab === "字段信息" && <SimpleList rows={data.fields} titleKey="business_meaning" detailKey="analysis_impact" />}
        {tab === "质量问题" && <SimpleList rows={data.quality_dimensions} titleKey="dimension" detailKey="finding" />}
        {tab === "支持能力" && <SimpleList rows={data.capabilities} titleKey="name" detailKey="status" />}
        {tab === "查询记录" && <SimpleList rows={data.query_runs} titleKey="query_name" detailKey="status" />}
      </div>
    </Card>
  );
}

function OverviewDetail({ data }: { data: DetailData }) {
  const q = data.quality ?? {};
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-line p-4">
        <h3 className="text-sm font-semibold">数据概况</h3>
        <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
          <Info label="所属项目" value="默认工作空间" />
          <Info label="数据量" value={`${data.dataset.row_count.toLocaleString()} 行`} />
          <Info label="来源" value={data.dataset.source_type} />
          <Info label="更新时间" value={data.dataset.updated_at.slice(0, 16).replace("T", " ")} />
          <Info label="时间范围" value={`${data.dataset.period_start} ~ ${data.dataset.period_end}`} wide />
          <Info label="原始数据" value="只读" />
        </div>
      </div>
      <div className="rounded-md border border-line p-4">
        <h3 className="text-sm font-semibold">质量评分</h3>
        <div className="mt-4 flex items-center gap-6">
          <div className="grid h-24 w-24 shrink-0 place-items-center rounded-full border-[9px] border-success/90">
            <span className="text-2xl font-semibold">{cn(q.quality_score)}<small className="text-xs">分</small></span>
          </div>
          <div className="flex-1 space-y-3">
            {[["完整性", q.completeness], ["一致性", q.validity], ["字段覆盖", q.field_coverage], ["时间覆盖", q.time_coverage]].map(([label, value]) => (
              <div key={String(label)}>
                <div className="flex justify-between text-xs"><span>{String(label)}</span><span>{cn(value)}%</span></div>
                <div className="mt-1 h-1.5 rounded bg-[#eef2f6]"><div className="h-full rounded bg-success" style={{ width: `${Number(value ?? 0)}%` }} /></div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="rounded-md border border-line p-4">
        <h3 className="text-sm font-semibold">支持分析能力</h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {data.capabilities.slice(0, 7).map((item, index) => (
            <Badge key={index} tone={item.status === "FULL" ? "green" : item.status === "PARTIAL" ? "orange" : "neutral"}>{cn(item.name)}</Badge>
          ))}
        </div>
      </div>
    </div>
  );
}

function Info({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return <div className={wide ? "col-span-2" : ""}><p className="text-xs text-muted">{label}</p><p className="mt-1 break-all font-medium">{value}</p></div>;
}

function SimpleList({ rows = [], titleKey, detailKey }: { rows?: Array<Record<string, unknown> | null | undefined>; titleKey: string; detailKey: string }) {
  const visibleRows = rows.filter((row): row is Record<string, unknown> => Boolean(row));
  return visibleRows.length ? (
    <div className="divide-y divide-line">
      {visibleRows.slice(0, 30).map((row, index) => (
        <div className="py-3" key={index}>
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium">{cn(row[titleKey])}</p>
            <Badge tone={row.status === "FULL" || row.status === "SUCCESS" ? "green" : row.status === "PARTIAL" ? "orange" : "neutral"}>{cn(row.status)}</Badge>
          </div>
          <p className="mt-1 text-xs leading-5 text-muted">{cn(row[detailKey])}</p>
        </div>
      ))}
    </div>
  ) : <EmptyState title="暂无记录" description="当前数据集没有此类记录。" />;
}

function SectionPreview({ nav, detail }: { nav: string; detail?: DetailData }) {
  if (nav === "容量治理" && detail) {
    return <CapacityPanel capacity={detail.capacity} />;
  }
  const mapping: Record<string, Array<Record<string, unknown>>> = {
    "导入记录": detail?.import_history ?? [],
    "数据质量": detail?.quality_dimensions ?? [],
    "字段管理": detail?.fields ?? [],
    "指标目录": detail?.metric_catalog ?? [],
    "规则目录": detail?.rule_catalog ?? [],
    "查询记录": detail?.query_runs ?? [],
    "汇率配置": detail?.fx_lineage ? [detail.fx_lineage] : [],
  };
  const titleKey = {
    "字段管理": "business_meaning",
    "数据质量": "dimension",
    "查询记录": "query_name",
    "指标目录": "name",
    "规则目录": "name",
    "汇率配置": "target_currency",
    "导入记录": "source_filename",
  }[nav] ?? "name";
  const detailKey = {
    "字段管理": "analysis_impact",
    "数据质量": "finding",
    "指标目录": "formula",
    "规则目录": "recovery_condition",
    "汇率配置": "fx_provider",
    "导入记录": "status",
  }[nav] ?? "detail";
  return (
    <div className="p-4">
      <SimpleList
        rows={mapping[nav] ?? []}
        titleKey={titleKey}
        detailKey={detailKey}
      />
    </div>
  );
}

function CapacityPanel({ capacity }: { capacity?: DetailData["capacity"] }) {
  if (!capacity) {
    return <EmptyState title="暂无容量数据" description="当前数据集还没有容量治理记录。" />;
  }
  const mb = (value: number) => `${(value / 1024 / 1024).toFixed(1)} MB`;
  const counts = Object.entries(capacity.record_counts ?? {});
  const statuses = Object.entries(capacity.scope_statuses ?? {});
  return (
    <div className="space-y-4 p-4">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-md border border-line p-4">
          <p className="text-xs text-muted">数据库总量</p>
          <p className="mt-2 text-xl font-semibold">{mb(capacity.database_bytes ?? 0)}</p>
        </div>
        <div className="rounded-md border border-line p-4">
          <p className="text-xs text-muted">READY Scope</p>
          <p className="mt-2 text-xl font-semibold">{capacity.scope_statuses?.READY ?? 0}</p>
        </div>
        <div className="rounded-md border border-line p-4">
          <p className="text-xs text-muted">默认保留</p>
          <p className="mt-2 text-xl font-semibold">{capacity.retention_policy?.keep_latest_default ?? 20} 个</p>
        </div>
      </div>
      <div className="rounded-md border border-line p-4">
        <h3 className="text-sm font-semibold">清理建议</h3>
        <div className="mt-3 space-y-2">
          {(capacity.cleanup_recommendations ?? []).map(item => (
            <p key={item} className="text-xs leading-5 text-muted">{item}</p>
          ))}
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-md border border-line p-4">
          <h3 className="text-sm font-semibold">Scope 状态</h3>
          <SimpleKeyValues rows={statuses} />
        </div>
        <div className="rounded-md border border-line p-4">
          <h3 className="text-sm font-semibold">派生对象</h3>
          <SimpleKeyValues rows={counts.slice(0, 12)} />
        </div>
      </div>
    </div>
  );
}

function SimpleKeyValues({ rows }: { rows: Array<[string, number]> }) {
  return rows.length ? (
    <div className="mt-3 divide-y divide-line">
      {rows.map(([key, value]) => (
        <div key={key} className="flex items-center justify-between py-2 text-xs">
          <span className="text-muted">{key}</span>
          <span className="font-medium tabular-nums">{Number(value).toLocaleString()}</span>
        </div>
      ))}
    </div>
  ) : <p className="mt-3 text-xs text-muted">暂无记录</p>;
}

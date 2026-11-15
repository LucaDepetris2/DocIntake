import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { DocumentSummary, Page, StatusCount } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { UploadButton } from "../components/UploadButton";
import { Async, Card, Confidence, StatusBadge, Tabs } from "../components/ui";
import { dateTime, label } from "../lib/format";
import { isProcessing, useMatters } from "../lib/queries";
import { useApi, usePolling } from "../lib/useApi";

const FILTERS = ["", "needs_review", "filed", "failed"] as const;
type Filter = (typeof FILTERS)[number];

/** Inbox and review queue are the same page: the review queue is ?status=needs_review. */
export function InboxPage() {
  const [params, setParams] = useSearchParams();
  const filter = (params.get("status") ?? "") as Filter;
  const navigate = useNavigate();
  const { byId: matters } = useMatters();

  const docs = useApi(
    () => api.get<Page<DocumentSummary>>(`/documents?limit=100${filter && `&status=${filter}`}`),
    [filter],
  );
  const stats = useApi(() => api.get<StatusCount[]>("/stats"), []);
  const counts = Object.fromEntries((stats.data ?? []).map((s) => [s.status, s.count]));
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  const refresh = () => {
    docs.reload();
    stats.reload();
  };
  // Keep refreshing while something on screen is still being processed by the workers.
  usePolling(refresh, 2000, (docs.data?.items ?? []).some((d) => isProcessing(d.status)));

  const columns: Column<DocumentSummary>[] = [
    { header: "File", cell: (d) => d.filed_name ?? d.original_filename },
    { header: "Type", cell: (d) => label(d.doc_type) },
    { header: "Conf.", cell: (d) => <Confidence value={d.classification_confidence} />, align: "right" },
    { header: "Case", cell: (d) => (d.matter_id ? matters.get(d.matter_id)?.case_number : "—") },
    { header: "Status", cell: (d) => <StatusBadge status={d.status} /> },
    { header: "Received", cell: (d) => dateTime(d.created_at) },
  ];

  return (
    <Card title="Documents" actions={<UploadButton onDone={refresh} />}>
      <Tabs
        options={FILTERS.map((f) => ({
          value: f,
          label: `${f ? label(f) : "All"} (${f ? (counts[f] ?? 0) : total})`,
        }))}
        value={filter}
        onChange={(f) => setParams(f ? { status: f } : {})}
      />
      <Async state={docs}>
        {(page) => (
          <DataTable
            rows={page.items}
            columns={columns}
            onRowClick={(d) => navigate(`/documents/${d.id}`)}
            empty="No documents. Upload some PDFs to start."
          />
        )}
      </Async>
    </Card>
  );
}

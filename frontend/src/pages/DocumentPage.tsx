import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { DOC_TYPES, type DocType, type DocumentDetail, type Matter } from "../api/types";
import { Async, Card, Confidence, ErrorText, Fields, StatusBadge } from "../components/ui";
import { dateTime, label } from "../lib/format";
import { isProcessing, useMatters } from "../lib/queries";
import { useAction, useApi, usePolling } from "../lib/useApi";

export function DocumentPage() {
  const { id = "" } = useParams();
  const doc = useApi(() => api.get<DocumentDetail>(`/documents/${id}`), [id]);
  const { matters, byId } = useMatters();
  usePolling(doc.reload, 2000, doc.data ? isProcessing(doc.data.status) : false);

  return (
    <Async state={doc}>
      {(d) => (
        <div className="grid">
          <div>
            <p>
              <Link to="/">← Inbox</Link>
            </p>
            <Card title={d.original_filename} actions={<StatusBadge status={d.status} />}>
              <Fields
                items={[
                  ["Type", label(d.doc_type)],
                  ["Classification", <Confidence value={d.classification_confidence} />],
                  ["Case", d.matter_id ? byId.get(d.matter_id)?.title : null],
                  ["Match", <Confidence value={d.match_confidence} />],
                  ["Filed as", d.filed_folder && `${d.filed_folder}/${d.filed_name}`],
                  ["Assignee", d.assignee],
                  ["Pages", d.page_count],
                  ["Review reason", d.review_reason],
                  ["Error", d.error],
                ]}
              />
            </Card>
            {d.status === "needs_review" && (
              <ReviewForm doc={d} matters={matters} onDone={doc.reload} />
            )}
            {d.status === "failed" && <RetryCard id={d.id} onDone={doc.reload} />}
            <Card title="Extracted entities">
              <Fields items={entityFields(d.entities)} />
            </Card>
            <Card title="Timeline">
              <ol className="timeline">
                {d.events.map((e) => (
                  <li key={e.created_at + e.to_status}>
                    <StatusBadge status={e.to_status} /> <span className="muted">{dateTime(e.created_at)}</span>
                    {e.detail && <div className="muted">{e.detail}</div>}
                  </li>
                ))}
              </ol>
            </Card>
          </div>
          <PdfPreview id={d.id} />
        </div>
      )}
    </Async>
  );
}

function entityFields(entities: DocumentDetail["entities"]): [string, string][] {
  if (!entities) return [];
  return Object.entries(entities)
    .filter(([key, value]) => key !== "match_candidates" && value != null)
    .map(([key, value]) => [label(key), formatEntity(value)]);
}

function formatEntity(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((v) => (Array.isArray(v) ? v.join(" v. ") : String(v))).join(", ") || "—";
  }
  if (typeof value === "object" && value !== null) {
    return Object.entries(value)
      .map(([k, v]) => `${label(k)}: ${formatEntity(v)}`)
      .join(" · ");
  }
  return String(value);
}

function ReviewForm({
  doc,
  matters,
  onDone,
}: {
  doc: DocumentDetail;
  matters: Matter[];
  onDone: () => void;
}) {
  // Pre-fill with the pipeline's best guesses: the human only confirms or corrects.
  const [docType, setDocType] = useState<DocType>(doc.doc_type ?? "other");
  const [matterId, setMatterId] = useState(doc.matter_id ?? "");
  const submit = useAction(async () => {
    await api.post(`/documents/${doc.id}/review`, { doc_type: docType, matter_id: matterId });
    onDone();
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit.run();
  };

  return (
    <Card title="Review">
      <form className="stack" onSubmit={onSubmit}>
        <label>
          Document type
          <select value={docType} onChange={(e) => setDocType(e.target.value as DocType)}>
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>
                {label(t)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Case
          <select value={matterId} onChange={(e) => setMatterId(e.target.value)} required>
            <option value="">Select a case…</option>
            {matters.map((m) => (
              <option key={m.id} value={m.id}>
                {m.case_number} — {m.title}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" disabled={submit.busy}>
          Confirm and file
        </button>
        <ErrorText error={submit.error} />
      </form>
    </Card>
  );
}

function RetryCard({ id, onDone }: { id: string; onDone: () => void }) {
  const retry = useAction(async () => {
    await api.post(`/documents/${id}/retry`);
    onDone();
  });
  return (
    <Card
      title="Processing failed"
      actions={
        <button className="primary" disabled={retry.busy} onClick={() => void retry.run()}>
          Retry
        </button>
      }
    >
      <ErrorText error={retry.error} />
    </Card>
  );
}

/** The PDF endpoint needs the auth header, so fetch it as a blob instead of a plain URL. */
function PdfPreview({ id }: { id: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let objectUrl: string | null = null;
    api.blob(`/documents/${id}/file`).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
    });
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [id]);
  return url ? <iframe className="pdf" src={url} title="Document preview" /> : null;
}

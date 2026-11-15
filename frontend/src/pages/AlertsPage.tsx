import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Alert } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { Async, Card, ErrorText } from "../components/ui";
import { day, daysUntil, label } from "../lib/format";
import { useMatters } from "../lib/queries";
import { useAction, useApi } from "../lib/useApi";

export function AlertsPage() {
  const alerts = useApi(() => api.get<Alert[]>("/alerts"), []);
  const { byId: matters } = useMatters();
  const resolve = useAction(async (id: string) => {
    await api.post(`/alerts/${id}/resolve`);
    alerts.reload();
  });

  const columns: Column<Alert>[] = [
    { header: "Due", cell: (a) => day(a.due_date) },
    { header: "In", cell: (a) => <DaysLeft iso={a.due_date} />, align: "right" },
    { header: "Deadline", cell: (a) => label(a.kind) },
    { header: "Case", cell: (a) => (a.matter_id ? matters.get(a.matter_id)?.case_number : "—") },
    { header: "Details", cell: (a) => a.description },
    { header: "Document", cell: (a) => <Link to={`/documents/${a.document_id}`}>Open</Link> },
    {
      header: "",
      cell: (a) => (
        <button disabled={resolve.busy} onClick={() => void resolve.run(a.id)}>
          Done
        </button>
      ),
    },
  ];

  return (
    <Card title="Upcoming deadlines">
      <ErrorText error={resolve.error} />
      <Async state={alerts}>
        {(rows) => <DataTable rows={rows} columns={columns} empty="No open deadlines." />}
      </Async>
    </Card>
  );
}

function DaysLeft({ iso }: { iso: string }) {
  const days = daysUntil(iso);
  const tone = days < 0 ? "bad" : days <= 7 ? "warn" : "";
  return <span className={`confidence ${tone}`}>{days < 0 ? `${-days}d late` : `${days}d`}</span>;
}

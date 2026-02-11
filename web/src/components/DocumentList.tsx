import { Document } from "../api/client";

interface Props {
  documents: Document[];
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    ready: "bg-green-50 text-green-700 ring-green-200",
    processing: "bg-yellow-50 text-yellow-700 ring-yellow-200",
    error: "bg-red-50 text-red-700 ring-red-200",
    pending: "bg-gray-50 text-gray-600 ring-gray-200",
  };

  const cls = colors[status] ?? colors.pending;

  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}
    >
      {status}
    </span>
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "--";
  return new Date(dateStr).toLocaleString();
}

export default function DocumentList({ documents }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[600px] text-sm text-left">
        <thead>
          <tr className="text-xs text-gray-500 uppercase tracking-wider">
            <th className="px-4 py-3 font-medium">Title</th>
            <th className="px-4 py-3 font-medium">Source</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Last synced</th>
            <th className="px-4 py-3 font-medium text-right">Segments</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {documents.map((doc) => (
            <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
              <td className="px-4 py-3 font-medium text-gray-800">
                {doc.title}
              </td>
              <td className="px-4 py-3 text-gray-500">{doc.source_type}</td>
              <td className="px-4 py-3">
                <StatusBadge status={doc.status} />
              </td>
              <td className="px-4 py-3 text-gray-500">
                {formatDate(doc.last_synced_at)}
              </td>
              <td className="px-4 py-3 text-right text-gray-500">
                {doc.segment_count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

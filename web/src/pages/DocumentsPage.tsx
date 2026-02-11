import { useState } from "react";
import DocumentList from "../components/DocumentList";
import { useDocuments } from "../hooks/useDocuments";
import { ingestFolder } from "../api/client";

export default function DocumentsPage() {
  const { documents, loading, error, refresh } = useDocuments();
  const [folderPath, setFolderPath] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [ingestMsg, setIngestMsg] = useState<string | null>(null);

  async function handleIngest() {
    if (!folderPath.trim()) return;
    setIngesting(true);
    setIngestMsg(null);
    try {
      const res = await ingestFolder(folderPath.trim());
      setIngestMsg(
        `Succeeded ${res.succeeded} of ${res.total} document(s).${res.failed ? ` Failed: ${res.failed}.` : ""}${res.skipped ? ` Skipped: ${res.skipped}.` : ""}`
      );
      setFolderPath("");
      setTimeout(() => refresh(), 2000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Ingest failed";
      setIngestMsg(msg);
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-3 border-b border-gray-200 bg-white">
        <h2 className="text-base font-semibold text-gray-800">Documents</h2>
      </header>

      <div className="flex-1 overflow-auto p-3 sm:p-6 space-y-6">
        {/* Ingest folder */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3">
            Ingest a folder
          </h3>
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              placeholder="/path/to/documents"
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              onKeyDown={(e) => e.key === "Enter" && handleIngest()}
            />
            <button
              onClick={handleIngest}
              disabled={ingesting || !folderPath.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              {ingesting ? "Ingesting..." : "Ingest"}
            </button>
          </div>
          {ingestMsg && (
            <p className="mt-2 text-xs text-gray-500">{ingestMsg}</p>
          )}
        </div>

        {/* Document list */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <h3 className="text-sm font-medium text-gray-700">
              All documents
            </h3>
            <button
              onClick={refresh}
              disabled={loading}
              className="text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
            >
              Refresh
            </button>
          </div>

          {error && (
            <p className="px-4 py-3 text-sm text-red-600">{error}</p>
          )}

          {loading && documents.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-gray-400">
              Loading...
            </p>
          ) : documents.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-gray-400">
              No documents ingested yet.
            </p>
          ) : (
            <DocumentList documents={documents} />
          )}
        </div>
      </div>
    </div>
  );
}

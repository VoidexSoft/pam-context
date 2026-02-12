import { useEffect, useState } from "react";
import DocumentList from "../components/DocumentList";
import { useDocuments } from "../hooks/useDocuments";
import { useIngestionTask } from "../hooks/useIngestionTask";
import { ingestFolder } from "../api/client";

export default function DocumentsPage() {
  const { documents, loading, error, refresh } = useDocuments();
  const { task, startPolling } = useIngestionTask();
  const [folderPath, setFolderPath] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Auto-refresh document list when task completes
  useEffect(() => {
    if (task?.status === "completed") {
      refresh();
    }
  }, [task?.status, refresh]);

  async function handleIngest() {
    if (!folderPath.trim()) return;
    setSubmitError(null);
    try {
      const res = await ingestFolder(folderPath.trim());
      setFolderPath("");
      startPolling(res.task_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to start ingestion";
      setSubmitError(msg);
    }
  }

  const isActive = task && (task.status === "pending" || task.status === "running");
  const progress =
    isActive && task.total_documents > 0
      ? Math.round((task.processed_documents / task.total_documents) * 100)
      : 0;

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
              disabled={!!isActive}
            />
            <button
              onClick={handleIngest}
              disabled={!!isActive || !folderPath.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              {isActive ? "Ingesting..." : "Ingest"}
            </button>
          </div>

          {/* Progress bar */}
          {isActive && (
            <div className="mt-3">
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>
                  {task.status === "pending" ? "Starting..." : `Processing ${task.processed_documents} of ${task.total_documents}`}
                </span>
                <span>{progress}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-indigo-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Completion summary */}
          {task?.status === "completed" && (
            <p className="mt-2 text-xs text-green-600">
              Succeeded {task.succeeded} of {task.total_documents} document(s).
              {task.failed > 0 && ` Failed: ${task.failed}.`}
              {task.skipped > 0 && ` Skipped: ${task.skipped}.`}
            </p>
          )}

          {/* Task error */}
          {task?.status === "failed" && (
            <p className="mt-2 text-xs text-red-600">
              Ingestion failed: {task.error || "Unknown error"}
            </p>
          )}

          {/* Submit error (e.g. invalid path) */}
          {submitError && (
            <p className="mt-2 text-xs text-red-600">{submitError}</p>
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

          {error ? (
            <div className="px-4 py-6 text-center">
              <p className="text-sm text-gray-500">
                {error.includes("500") || error.includes("fetch")
                  ? "Could not reach the API server. Is the backend running?"
                  : error}
              </p>
            </div>
          ) : loading && documents.length === 0 ? (
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

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getSegment, SegmentDetail } from "../api/client";

interface Props {
  segmentId: string | null;
  onClose: () => void;
}

export default function SourceViewer({ segmentId, onClose }: Props) {
  const [segment, setSegment] = useState<SegmentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!segmentId) {
      setSegment(null);
      return;
    }

    setLoading(true);
    setError(null);
    getSegment(segmentId)
      .then(setSegment)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [segmentId]);

  if (!segmentId) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed top-0 right-0 h-full w-full max-w-md bg-white shadow-xl z-50 flex flex-col border-l border-gray-200 animate-slide-in">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <h3 className="text-sm font-semibold text-gray-800">Source</h3>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100"
            aria-label="Close"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <span className="inline-block w-2 h-2 bg-indigo-400 rounded-full animate-pulse" />
              Loading source...
            </div>
          )}

          {error && (
            <div className="text-sm text-red-500 bg-red-50 rounded-lg p-3">{error}</div>
          )}

          {segment && !loading && (
            <div className="space-y-4">
              {/* Metadata */}
              <div className="space-y-2">
                {segment.document_title && (
                  <div>
                    <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Document</span>
                    <p className="text-sm font-medium text-gray-800 mt-0.5">{segment.document_title}</p>
                  </div>
                )}

                {segment.section_path && (
                  <div>
                    <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Section</span>
                    <p className="text-sm text-gray-600 mt-0.5 font-mono">{segment.section_path}</p>
                  </div>
                )}

                <div className="flex gap-3">
                  {segment.source_type && (
                    <div>
                      <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Type</span>
                      <p className="text-xs mt-0.5">
                        <span className="inline-block rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">
                          {segment.source_type}
                        </span>
                      </p>
                    </div>
                  )}
                  <div>
                    <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">Position</span>
                    <p className="text-xs mt-0.5 text-gray-600">#{segment.position}</p>
                  </div>
                </div>

                {segment.source_url && (
                  <a
                    href={segment.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                    Open original
                  </a>
                )}
              </div>

              {/* Divider */}
              <hr className="border-gray-200" />

              {/* Content */}
              <div className="prose prose-sm max-w-none text-gray-700">
                <ReactMarkdown>{segment.content}</ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

import { ChatFilters } from "../api/client";

const SOURCE_TYPES = [
  { value: "", label: "All sources" },
  { value: "markdown", label: "Markdown" },
  { value: "google_doc", label: "Google Docs" },
  { value: "google_sheets", label: "Google Sheets" },
];

interface Props {
  filters: ChatFilters;
  onChange: (filters: ChatFilters) => void;
}

export default function SearchFilters({ filters, onChange }: Props) {
  return (
    <div className="flex items-center gap-2 px-3 sm:px-6 py-2 border-b border-gray-100 bg-gray-50/50">
      <span className="text-xs text-gray-400 shrink-0">Filter:</span>
      <div className="flex gap-1.5 flex-wrap">
        {SOURCE_TYPES.map((type) => {
          const isActive = (filters.source_type || "") === type.value;
          return (
            <button
              key={type.value}
              onClick={() =>
                onChange({
                  ...filters,
                  source_type: type.value || undefined,
                })
              }
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                isActive
                  ? "bg-indigo-100 text-indigo-700 ring-1 ring-indigo-200"
                  : "bg-white text-gray-500 ring-1 ring-gray-200 hover:bg-gray-50"
              }`}
            >
              {type.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

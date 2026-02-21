import { useCallback, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { getGraphEntities, type EntityListItem } from "../../api/client";

const ENTITY_TYPE_COLORS: Record<string, string> = {
  Person: "#6366f1",
  Team: "#8b5cf6",
  Project: "#3b82f6",
  Technology: "#10b981",
  Process: "#f59e0b",
  Concept: "#ec4899",
  Asset: "#6b7280",
};

interface EntitySearchProps {
  onEntitySelect: (name: string) => void;
}

export default function EntitySearch({ onEntitySelect }: EntitySearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<EntityListItem[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const doSearch = useCallback(async (searchQuery: string) => {
    if (searchQuery.trim().length === 0) {
      setResults([]);
      setShowDropdown(false);
      return;
    }

    setLoading(true);
    try {
      const response = await getGraphEntities({ limit: 50 });
      const filtered = response.entities.filter((e) =>
        e.name.toLowerCase().includes(searchQuery.toLowerCase())
      );
      setResults(filtered.slice(0, 10));
      setShowDropdown(true);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      doSearch(query);
    }, 300);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [query, doSearch]);

  const handleSelect = useCallback(
    (name: string) => {
      setQuery(name);
      setShowDropdown(false);
      onEntitySelect(name);
    },
    [onEntitySelect]
  );

  const handleBlur = useCallback(() => {
    // Small delay to allow click events to fire on dropdown items
    setTimeout(() => {
      setShowDropdown(false);
    }, 200);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => {
            if (results.length > 0) setShowDropdown(true);
          }}
          onBlur={handleBlur}
          placeholder="Search entities..."
          className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
        {loading && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {showDropdown && results.length > 0 && (
        <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-y-auto">
          {results.map((entity) => (
            <button
              key={entity.uuid}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleSelect(entity.name)}
              className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 transition-colors"
            >
              <span className="font-medium text-gray-800 truncate flex-1">
                {entity.name}
              </span>
              <span
                className="shrink-0 text-xs font-medium px-2 py-0.5 rounded-full text-white"
                style={{
                  backgroundColor:
                    ENTITY_TYPE_COLORS[entity.entity_type] ?? "#6b7280",
                }}
              >
                {entity.entity_type}
              </span>
            </button>
          ))}
        </div>
      )}

      {showDropdown && results.length === 0 && query.trim().length > 0 && !loading && (
        <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2">
          <p className="text-sm text-gray-400">No entities found</p>
        </div>
      )}
    </div>
  );
}

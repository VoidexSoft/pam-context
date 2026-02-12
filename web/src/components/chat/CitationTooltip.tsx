import { Citation } from "../../api/client";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";

interface Props {
  citation: Citation;
  index: number;
  onViewSource?: (segmentId: string) => void;
}

export default function CitationTooltip({ citation, index, onViewSource }: Props) {
  function handleClick() {
    if (citation.segment_id && onViewSource) {
      onViewSource(citation.segment_id);
    }
  }

  const sourceIcon = citation.source_url ? (
    <svg className="h-3.5 w-3.5 text-zinc-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
    </svg>
  ) : (
    <svg className="h-3.5 w-3.5 text-zinc-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  );

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={handleClick}
            className="inline-flex items-center justify-center h-5 min-w-[1.25rem] rounded bg-indigo-100 px-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-200 transition-colors cursor-pointer dark:bg-indigo-900/40 dark:text-indigo-300 dark:hover:bg-indigo-800/50"
          >
            {index}
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="max-w-xs bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-lg p-3 rounded-lg"
        >
          <div className="flex items-start gap-2">
            {sourceIcon}
            <div className="min-w-0">
              <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">
                {citation.title}
              </p>
              {citation.source_url && (
                <p className="text-xs text-zinc-500 dark:text-zinc-400 truncate mt-0.5">
                  {citation.source_url}
                </p>
              )}
            </div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

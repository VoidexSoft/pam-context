import React, { useCallback, useMemo } from "react";
import type { Components } from "react-markdown";
import { Citation } from "../api/client";
import CodeBlock from "../components/chat/CodeBlock";
import CitationTooltip from "../components/chat/CitationTooltip";

interface UseMarkdownComponentsOptions {
  citations?: Citation[];
  onViewSource?: (segmentId: string) => void;
}

export function useMarkdownComponents({
  citations,
  onViewSource,
}: UseMarkdownComponentsOptions = {}): Components {
  const renderCode = useCallback(
    ({ className, children, ...rest }: React.ComponentPropsWithoutRef<"code"> & { inline?: boolean }) => {
      // react-markdown v6+ passes node; detect inline via absence of className on code inside pre
      const isInline = !className;
      return (
        <CodeBlock className={className} inline={isInline} {...rest}>
          {children}
        </CodeBlock>
      );
    },
    []
  );

  const renderAnchor = useCallback(
    ({ href, children, ...rest }: React.ComponentPropsWithoutRef<"a">) => {
      // Check if this is a citation link like [1], [2]
      const text = typeof children === "string" ? children : "";
      const citationMatch = text.match(/^\[(\d+)\]$/);

      if (citationMatch && citations?.length) {
        const idx = parseInt(citationMatch[1], 10);
        const citation = citations[idx - 1];
        if (citation) {
          return (
            <CitationTooltip
              citation={citation}
              index={idx}
              onViewSource={onViewSource}
            />
          );
        }
      }

      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-indigo-600 hover:text-indigo-800 underline decoration-indigo-300 dark:text-indigo-400 dark:hover:text-indigo-300"
          {...rest}
        >
          {children}
        </a>
      );
    },
    [citations, onViewSource]
  );

  const renderTable = useCallback(
    ({ children, ...rest }: React.ComponentPropsWithoutRef<"table">) => (
      <div className="my-3 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
        <table className="min-w-full divide-y divide-zinc-200 dark:divide-zinc-700 text-sm" {...rest}>
          {children}
        </table>
      </div>
    ),
    []
  );

  const renderTh = useCallback(
    ({ children, ...rest }: React.ComponentPropsWithoutRef<"th">) => (
      <th className="bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-left text-xs font-semibold text-zinc-600 dark:text-zinc-300 uppercase tracking-wider" {...rest}>
        {children}
      </th>
    ),
    []
  );

  const renderTd = useCallback(
    ({ children, ...rest }: React.ComponentPropsWithoutRef<"td">) => (
      <td className="px-3 py-2 text-zinc-700 dark:text-zinc-300" {...rest}>
        {children}
      </td>
    ),
    []
  );

  const renderPre = useCallback(
    ({ children }: React.ComponentPropsWithoutRef<"pre">) => <>{children}</>,
    []
  );

  return useMemo(
    () => ({
      code: renderCode,
      a: renderAnchor,
      table: renderTable,
      th: renderTh,
      td: renderTd,
      pre: renderPre,
    }),
    [renderCode, renderAnchor, renderTable, renderTh, renderTd, renderPre]
  );
}

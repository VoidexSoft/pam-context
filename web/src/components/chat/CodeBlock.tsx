import React, { useCallback, useState } from "react";

interface CodeBlockProps {
  className?: string;
  children?: React.ReactNode;
  inline?: boolean;
}

function extractText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(extractText).join("");
  if (React.isValidElement(children) && children.props?.children) {
    return extractText(children.props.children);
  }
  return String(children ?? "");
}

function CodeBlock({ className, children, inline, ...rest }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const language = className?.replace("language-", "") ?? "";
  const code = extractText(children).replace(/\n$/, "");

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  // Inline code
  if (inline) {
    return (
      <code
        className="rounded bg-zinc-100 px-1.5 py-0.5 text-[0.85em] font-mono text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200"
        {...rest}
      >
        {children}
      </code>
    );
  }

  // Block code
  return (
    <div className="group relative my-3 overflow-hidden rounded-lg border border-zinc-200 bg-zinc-950 dark:border-zinc-700">
      {/* Header bar */}
      <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4 py-1.5">
        <span className="text-xs font-medium text-zinc-400">
          {language || "text"}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
          aria-label="Copy code"
        >
          {copied ? (
            <>
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              Copied
            </>
          ) : (
            <>
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              Copy
            </>
          )}
        </button>
      </div>

      {/* Code content */}
      <div className="overflow-x-auto p-4 code-scrollbar">
        <pre className="!m-0 !bg-transparent !p-0">
          <code className={`${className ?? ""} !bg-transparent text-sm leading-relaxed`} {...rest}>
            {children}
          </code>
        </pre>
      </div>
    </div>
  );
}

export default React.memo(CodeBlock);

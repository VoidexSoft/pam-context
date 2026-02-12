/**
 * Markdown preprocessing pipeline.
 * Adapted from Onyx's codeUtils.ts and markdownUtils.tsx (MIT license).
 */

const CODE_BLOCK_REGEX = /```[\s\S]*?```/g;

/**
 * Protect code blocks from LaTeX processing by replacing them with placeholders.
 */
function extractCodeBlocks(text: string): { cleaned: string; blocks: string[] } {
  const blocks: string[] = [];
  const cleaned = text.replace(CODE_BLOCK_REGEX, (match) => {
    blocks.push(match);
    return `%%CODE_BLOCK_${blocks.length - 1}%%`;
  });
  return { cleaned, blocks };
}

function restoreCodeBlocks(text: string, blocks: string[]): string {
  return text.replace(/%%CODE_BLOCK_(\d+)%%/g, (_, idx) => blocks[Number(idx)]);
}

/**
 * Convert LaTeX delimiters to standard $/$$ and escape currency amounts.
 */
function preprocessLaTeX(text: string): string {
  const { cleaned, blocks } = extractCodeBlocks(text);

  let result = cleaned;

  // Convert \[...\] to $$...$$
  result = result.replace(/\\\[([\s\S]*?)\\\]/g, (_, content) => `$$${content}$$`);

  // Convert \(...\) to $...$
  result = result.replace(/\\\(([\s\S]*?)\\\)/g, (_, content) => `$${content}$`);

  // Escape currency: $123 or $1,234.56 → \$amount
  result = result.replace(/\$(\d[\d,]*\.?\d*)/g, "\\$$1");

  return restoreCodeBlocks(result, blocks);
}

/**
 * Add language labels to bare code fences (``` without language).
 * Helps rehype-highlight produce better results.
 */
function addLanguageLabels(text: string): string {
  return text.replace(/```\n/g, "```text\n");
}

/**
 * Main entry point: preprocess markdown content for rich rendering.
 */
export function processContent(text: string): string {
  let result = text;
  result = addLanguageLabels(result);
  result = preprocessLaTeX(result);
  return result;
}

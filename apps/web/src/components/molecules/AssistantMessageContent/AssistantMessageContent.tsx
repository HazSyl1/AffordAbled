import type { ReactNode } from 'react';

interface AssistantMessageContentProps {
  content: string;
}

type ContentBlock =
  | { kind: 'text'; content: string }
  | { kind: 'table'; headers: string[]; rows: string[][] };

function splitTableRow(line: string): string[] {
  const normalized = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return normalized.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, '|'));
}

function isTableSeparator(line: string): boolean {
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function parseContent(content: string): ContentBlock[] {
  const lines = content.split(/\r?\n/);
  const blocks: ContentBlock[] = [];
  let textLines: string[] = [];
  let index = 0;

  const flushText = () => {
    if (textLines.length > 0) {
      blocks.push({ kind: 'text', content: textLines.join('\n') });
      textLines = [];
    }
  };

  while (index < lines.length) {
    if (index + 1 < lines.length && lines[index].includes('|') && isTableSeparator(lines[index + 1])) {
      const headers = splitTableRow(lines[index]);
      const rows: string[][] = [];
      index += 2;

      while (index < lines.length && lines[index].includes('|')) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }

      flushText();
      blocks.push({ kind: 'table', headers, rows });
      continue;
    }

    textLines.push(lines[index]);
    index += 1;
  }

  flushText();
  return blocks;
}

function renderBlock(block: ContentBlock, index: number): ReactNode {
  if (block.kind === 'text') {
    return (
      <p key={`text-${index}`} className='whitespace-pre-line'>
        {block.content}
      </p>
    );
  }

  return (
    <div key={`table-${index}`} className='max-w-full overflow-x-auto'>
      <table className='w-full border-collapse text-left text-xs sm:text-sm'>
        <thead>
          <tr>
            {block.headers.map((header, headerIndex) => (
              <th
                key={`${header}-${headerIndex}`}
                className='whitespace-nowrap border-b border-(--bg-border) px-2 py-2 font-semibold text-(--text-secondary)'
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`} className='border-b border-(--bg-border) last:border-b-0'>
              {block.headers.map((_, cellIndex) => (
                <td key={`cell-${rowIndex}-${cellIndex}`} className='px-2 py-2 text-(--text-primary)'>
                  {row[cellIndex] ?? ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AssistantMessageContent({ content }: AssistantMessageContentProps) {
  return <div className='space-y-2'>{parseContent(content).map(renderBlock)}</div>;
}

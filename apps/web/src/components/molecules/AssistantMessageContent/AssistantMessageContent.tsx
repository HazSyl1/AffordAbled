import { useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { useLazyGetTransactionExportDownloadUrlQuery } from '../../../features/transactions/transactionFilesApi';
import { API_BASE_URL } from '../../../lib/env';

interface AssistantMessageContentProps {
  content: string;
}

type ContentBlock =
  | { kind: 'text'; content: string }
  | { kind: 'table'; headers: string[]; rows: string[][] }
  | { kind: 'export'; exportId: string }
  | { kind: 'settlement'; draftId: string };

const exportMarker = /^\[\[export:([0-9a-fA-F-]{36})\]\]$/;
const settlementMarker = /^\[\[settlement:([0-9a-fA-F-]{36})\]\]$/;

function ExportDownloadButton({ exportId }: { exportId: string }) {
  const [getDownloadUrl, { isFetching }] = useLazyGetTransactionExportDownloadUrlQuery();
  const [error, setError] = useState('');

  const handleDownload = async () => {
    setError('');
    try {
      const result = await getDownloadUrl(exportId, false).unwrap();
      const anchor = document.createElement('a');
      anchor.href = result.download_url.startsWith('http')
        ? result.download_url : `${API_BASE_URL}${result.download_url}`;
      anchor.rel = 'noopener noreferrer';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch {
      setError('This report is no longer available. Request a new export.');
    }
  };

  return (
    <div>
      <button type='button' disabled={isFetching} onClick={() => void handleDownload()}
        className='rounded-lg bg-[var(--brand-primary)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-60'>
        {isFetching ? 'Preparing download…' : 'Download report'}
      </button>
      {error && <p role='alert' className='mt-1 text-sm text-[var(--negative)]'>{error}</p>}
    </div>
  );
}

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
    const exportMatch = exportMarker.exec(lines[index].trim());
    if (exportMatch) {
      flushText();
      blocks.push({ kind: 'export', exportId: exportMatch[1] });
      index += 1;
      continue;
    }
    const settlementMatch = settlementMarker.exec(lines[index].trim());
    if (settlementMatch) {
      flushText();
      blocks.push({ kind: 'settlement', draftId: settlementMatch[1] });
      index += 1;
      continue;
    }
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
  if (block.kind === 'export') {
    return <ExportDownloadButton key={`export-${index}`} exportId={block.exportId} />;
  }
  if (block.kind === 'settlement') {
    return <Link key={`settlement-${index}`} to={`/splits?draft=${block.draftId}`}
      className='inline-block rounded-lg bg-[var(--brand-primary)] px-3 py-2 text-sm font-semibold text-white'>
      Review settlement
    </Link>;
  }
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

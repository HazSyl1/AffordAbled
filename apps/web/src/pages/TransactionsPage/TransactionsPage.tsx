import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Download, Upload } from 'lucide-react';

import { Button } from '../../components/atoms/Button';
import { Card } from '../../components/atoms/Card';
import { BottomSheet } from '../../components/molecules/BottomSheet';
import { ThemedSelect } from '../../components/molecules/ThemedSelect';
import { CreateTransactionForm } from '../../components/organisms/CreateTransactionForm';
import type { CreateTransactionFormValues } from '../../components/organisms/CreateTransactionForm/CreateTransactionForm.schema';
import { TransactionList } from '../../components/organisms/TransactionList';
import { useListTransactionsQuery } from '../../features/transactions/transactionsApi';
import type { Transaction } from '../../features/transactions/transactionsApi';
import {
  useConfirmTransactionImportMutation,
  useCreateTransactionExportMutation,
  usePreviewTransactionImportMutation,
} from '../../features/transactions/transactionFilesApi';
import type { TransactionExportFormat, TransactionImportPreview } from '../../features/transactions/transactionFilesApi';
import { SHEET_TITLES } from '../../constants';
import { API_BASE_URL } from '../../lib/env';
import { formatPaiseAsInr } from '../../lib/money';

function mapTransactionToFormValues(transaction: Transaction): Partial<CreateTransactionFormValues> {
  return {
    accountId: transaction.account_id,
    type: transaction.type,
    amountRupees: (transaction.amount_paise / 100).toFixed(2),
    occurredAt: transaction.occurred_at,
    categoryId: transaction.category_id ?? '',
    toAccountId: transaction.to_account_id ?? '',
    merchant: transaction.merchant ?? '',
    note: transaction.note ?? '',
  };
}

function errorDetail(error: unknown): string {
  if (error && typeof error === 'object' && 'data' in error) {
    const data = error.data as { detail?: unknown } | undefined;
    if (typeof data?.detail === 'string') return data.detail;
  }
  return 'Something went wrong. Please try again.';
}

const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

export function TransactionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTransactionId = searchParams.get('transactionId');
  const { data: transactions } = useListTransactionsQuery();
  const [isAddTransactionSheetOpen, setIsAddTransactionSheetOpen] = useState(false);
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<TransactionExportFormat>('xlsx');
  const [exportFrom, setExportFrom] = useState('');
  const [exportTo, setExportTo] = useState('');
  const [exportError, setExportError] = useState('');
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<TransactionImportPreview | null>(null);
  const [importError, setImportError] = useState('');
  const [importSuccess, setImportSuccess] = useState('');
  const [createExport, { isLoading: exporting }] = useCreateTransactionExportMutation();
  const [previewImport, { isLoading: previewing }] = usePreviewTransactionImportMutation();
  const [confirmImport, { isLoading: importing }] = useConfirmTransactionImportMutation();
  const transactionBeingEdited = requestedTransactionId
    ? transactions?.find((item) => item.id === requestedTransactionId) ?? null
    : selectedTransaction;

  const editInitialValues = useMemo(
    () => (transactionBeingEdited ? mapTransactionToFormValues(transactionBeingEdited) : undefined),
    [transactionBeingEdited],
  );

  const summary = useMemo(() => {
    let expensePaise = 0;
    let incomePaise = 0;
    let transferPaise = 0;

    for (const transaction of transactions ?? []) {
      if (transaction.deleted_at !== null) {
        continue;
      }

      if (transaction.type === 'expense') {
        expensePaise += transaction.amount_paise;
      } else if (transaction.type === 'income' || transaction.type === 'refund') {
        incomePaise += transaction.amount_paise;
      } else if (transaction.type === 'transfer') {
        transferPaise += transaction.amount_paise;
      }
    }

    return {
      expensePaise,
      incomePaise,
      transferPaise,
      netPaise: incomePaise - expensePaise,
    };
  }, [transactions]);

  const handleOpenEditSheet = (transaction: Transaction) => {
    setSelectedTransaction(transaction);
  };

  const handleCloseEditSheet = () => {
    setSelectedTransaction(null);
    if (requestedTransactionId) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.delete('transactionId');
        return next;
      }, { replace: true });
    }
  };

  const handleExport = async () => {
    setExportError('');
    try {
      const result = await createExport({
        format: exportFormat,
        date_from: exportFrom || undefined,
        date_to: exportTo || undefined,
        timezone,
      }).unwrap();
      const anchor = document.createElement('a');
      anchor.href = result.download_url.startsWith('http')
        ? result.download_url
        : `${API_BASE_URL}${result.download_url}`;
      anchor.download = result.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setIsExportOpen(false);
    } catch (error) {
      setExportError(errorDetail(error));
    }
  };

  const handlePreviewImport = async () => {
    if (!importFile) return;
    setImportError('');
    setImportSuccess('');
    try {
      setImportPreview(await previewImport({ file: importFile, timezone }).unwrap());
    } catch (error) {
      setImportPreview(null);
      setImportError(errorDetail(error));
    }
  };

  const handleConfirmImport = async () => {
    if (!importFile || !importPreview) return;
    setImportError('');
    try {
      const result = await confirmImport({ file: importFile, timezone, previewHash: importPreview.file_hash }).unwrap();
      setImportSuccess(`${result.imported_count} transactions imported.`);
      setImportPreview(null);
      setImportFile(null);
    } catch (error) {
      setImportError(errorDetail(error));
    }
  };

  const downloadImportTemplate = () => {
    const template = 'occurred_at,type,amount_paise,account,category,to_account,merchant,note\r\n';
    const objectUrl = URL.createObjectURL(new Blob([template], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = 'affordabled-import-template.csv';
    anchor.click();
    URL.revokeObjectURL(objectUrl);
  };

  return (
    <div className='mx-auto w-full max-w-[1200px] px-4 py-4 md:px-6 md:py-6'>
      <header className='sticky top-[env(safe-area-inset-top)] z-10 -mx-4 mb-4 border-b border-[var(--bg-border)] bg-[color:rgba(9,9,11,0.9)] px-4 py-4 backdrop-blur-xl md:static md:mx-0 md:border-none md:bg-transparent md:px-0 md:py-0'>
        <div className='flex items-start justify-between gap-3'>
          <div className='min-w-0'>
            <h1 className='text-xl font-bold text-[var(--text-primary)]'>Transactions</h1>
            <p className='text-xs text-[var(--text-secondary)]'>Review spending, income, and transfers in one place. Click a transaction to edit it or add a split.</p>
          </div>

          <div className='flex shrink-0 items-start gap-1.5'>
            <Button type='button' className='!min-h-0 !w-auto flex-col !gap-0.5 !rounded-lg !px-2.5 !py-1.5 !text-[11px] !leading-none'
              onClick={() => setIsImportOpen(true)}>
              <Upload size={15} aria-hidden='true' />
              <span>Import</span>
            </Button>
            <Button type='button' className='!min-h-0 !w-auto flex-col !gap-0.5 !rounded-lg !px-2.5 !py-1.5 !text-[11px] !leading-none'
              onClick={() => setIsExportOpen(true)}>
              <Download size={15} aria-hidden='true' />
              <span>Export</span>
            </Button>
            <Button type='button' className='w-auto px-3 lg:hidden' onClick={() => setIsAddTransactionSheetOpen(true)}>
              + Add
            </Button>
          </div>
        </div>
      </header>

      <section className='mb-5'>
        <div className='flex gap-3 overflow-x-auto pb-1 scrollbar-none'>
          <Card className='min-w-[120px] flex-shrink-0 p-3'>
            <p className='text-lg font-bold text-[var(--negative)]'>-{formatPaiseAsInr(summary.expensePaise)}</p>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Expenses</p>
          </Card>
          <Card className='min-w-[120px] flex-shrink-0 p-3'>
            <p className='text-lg font-bold text-[var(--positive)]'>+{formatPaiseAsInr(summary.incomePaise)}</p>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Income</p>
          </Card>
          <Card className='min-w-[120px] flex-shrink-0 p-3'>
            <p className='text-lg font-bold text-[var(--text-primary)]'>{formatPaiseAsInr(summary.netPaise)}</p>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Net</p>
          </Card>
          <Card className='min-w-[120px] flex-shrink-0 p-3'>
            <p className='text-lg font-bold text-[var(--info)]'>{formatPaiseAsInr(summary.transferPaise)}</p>
            <p className='mt-0.5 text-xs text-[var(--text-muted)]'>Transfers</p>
          </Card>
        </div>
      </section>

      <div className='grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start'>
        <section>
          <Card className='p-4 md:p-5'>
            <TransactionList onTransactionSelect={handleOpenEditSheet} />
          </Card>
        </section>

        <section className='hidden lg:block lg:sticky lg:top-6'>
          <Card className='p-5'>
            <CreateTransactionForm mode='page' />
          </Card>
        </section>
      </div>

      <BottomSheet
        isOpen={isExportOpen}
        onClose={() => setIsExportOpen(false)}
        title='Export transactions'
      >
        <div className='space-y-4'>
          <p className='text-sm text-[var(--text-secondary)]'>Download your transactions as a spreadsheet or PDF report. Internal IDs and notes are excluded.</p>
          <div>
            <label htmlFor='export-format' className='mb-1 block text-sm text-[var(--text-secondary)]'>Format</label>
            <ThemedSelect id='export-format' value={exportFormat} placeholder='Choose a format'
              options={[{ label: 'Excel (.xlsx)', value: 'xlsx' }, { label: 'CSV (.csv)', value: 'csv' },
                { label: 'PDF (.pdf)', value: 'pdf' }]}
              onChange={(value) => setExportFormat(value as TransactionExportFormat)} />
          </div>
          <div className='grid grid-cols-2 gap-3'>
            <label className='text-sm text-[var(--text-secondary)]'>From (optional)
              <input type='date' value={exportFrom} onChange={(event) => setExportFrom(event.target.value)}
                className='mt-1 min-h-12 w-full rounded-xl border border-[var(--bg-border)] bg-[var(--bg-surface)] px-3 text-[var(--text-primary)]' />
            </label>
            <label className='text-sm text-[var(--text-secondary)]'>To (optional)
              <input type='date' value={exportTo} onChange={(event) => setExportTo(event.target.value)}
                className='mt-1 min-h-12 w-full rounded-xl border border-[var(--bg-border)] bg-[var(--bg-surface)] px-3 text-[var(--text-primary)]' />
            </label>
          </div>
          <p className='text-xs text-[var(--text-muted)]'>Leave dates empty to export all transactions. Downloads remain available for 24 hours.</p>
          {exportError && <p role='alert' className='text-sm text-[var(--negative)]'>{exportError}</p>}
          <Button type='button' isLoading={exporting} onClick={() => void handleExport()}>Download export</Button>
        </div>
      </BottomSheet>

      <BottomSheet
        isOpen={isImportOpen}
        onClose={() => { setIsImportOpen(false); setImportPreview(null); setImportError(''); }}
        title='Import transactions'
      >
        <div className='space-y-4'>
          <p className='text-sm text-[var(--text-secondary)]'>Upload a CSV or Excel file. Check the import preview before adding transactions.</p>
          <button type='button' className='text-sm font-medium text-[var(--brand-primary)] underline'
            onClick={downloadImportTemplate}>Download CSV template</button>
          <input type='file' accept='.csv,.xlsx' aria-label='Transaction file'
            className='block w-full text-sm text-[var(--text-secondary)] file:mr-3 file:rounded-lg file:border-0 file:bg-[var(--bg-elevated)] file:px-3 file:py-2 file:text-[var(--text-primary)]'
            onChange={(event) => { setImportFile(event.target.files?.[0] ?? null); setImportPreview(null);
              setImportError(''); setImportSuccess(''); }} />
          <p className='text-xs text-[var(--text-muted)]'>Use your existing account and category names. No transactions are added until you confirm.</p>
          {importFile && <Button type='button' variant='secondary' isLoading={previewing}
            onClick={() => void handlePreviewImport()}>Preview import</Button>}
          {importPreview && <div className='space-y-3 rounded-xl border border-[var(--bg-border)] p-3'>
            <p className='text-sm font-semibold text-[var(--text-primary)]'>
              {importPreview.valid_count} of {importPreview.row_count} rows ready
            </p>
            <p className='text-xs text-[var(--text-muted)]'>Only identical files are blocked. An edited file may add transactions that already exist.</p>
            {importPreview.already_imported && <p role='alert' className='text-sm text-[var(--negative)]'>This file is already in your account.</p>}
            {importPreview.errors.length > 0 && <ul className='max-h-32 overflow-auto text-sm text-[var(--negative)]'>
              {importPreview.errors.map((error) => <li key={error.row_number}>Row {error.row_number}: {error.message}</li>)}
            </ul>}
            <div className='max-h-52 overflow-auto text-xs text-[var(--text-secondary)]'>
              {importPreview.preview_rows.map((row) => <div key={row.row_number}
                className='border-b border-[var(--bg-border)] py-2'>
                Row {row.row_number}: {row.type} {row.amount_paise !== undefined
                  ? formatPaiseAsInr(row.amount_paise) : row.amount} · {row.account} · {row.category || row.merchant}
              </div>)}
              {importPreview.row_count > importPreview.preview_rows.length &&
                <p className='py-2'>Showing the first {importPreview.preview_rows.length} rows.</p>}
            </div>
            <Button type='button' isLoading={importing}
              disabled={importPreview.already_imported || importPreview.valid_count !== importPreview.row_count}
              onClick={() => void handleConfirmImport()}>Confirm import</Button>
          </div>}
          {importError && <p role='alert' className='text-sm text-[var(--negative)]'>{importError}</p>}
          {importSuccess && <p role='status' className='text-sm text-[var(--positive)]'>{importSuccess}</p>}
        </div>
      </BottomSheet>

      <BottomSheet
        isOpen={isAddTransactionSheetOpen}
        onClose={() => setIsAddTransactionSheetOpen(false)}
        title={SHEET_TITLES.addTransaction}
      >
        <CreateTransactionForm
          mode='sheet'
          showHeading={false}
          onSuccess={() => setIsAddTransactionSheetOpen(false)}
        />
      </BottomSheet>

      <BottomSheet
        isOpen={Boolean(transactionBeingEdited)}
        onClose={handleCloseEditSheet}
        title={SHEET_TITLES.editTransaction}
      >
        {transactionBeingEdited ? (
          <CreateTransactionForm
            mode='sheet'
            showHeading={false}
            transactionId={transactionBeingEdited.id}
            initialValues={editInitialValues}
            submitLabel='Save changes'
            onSuccess={handleCloseEditSheet}
          />
        ) : null}
      </BottomSheet>
    </div>
  );
}

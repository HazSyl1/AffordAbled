import { useState } from 'react';
import { createPortal } from 'react-dom';
import {
  useDeleteTransactionMutation, useGetTransactionDeletionStatusQuery,
} from '../../../features/transactions/transactionsApi';

export function TransactionDeleteAction({ transactionId, onDeleted }: {
  transactionId: string; onDeleted?: () => void;
}) {
  const { data: eligibility } = useGetTransactionDeletionStatusQuery(transactionId);
  const [remove, { isLoading }] = useDeleteTransactionMutation();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [deleted, setDeleted] = useState(false);
  if (deleted) return null;
  return <>
    {eligibility?.can_delete && <button type='button'
      className='rounded-full border border-red-400/50 bg-red-500/10 px-3 py-1 text-xs font-semibold text-red-500 hover:bg-red-500 hover:text-white'
      onKeyDown={(event) => event.stopPropagation()}
      onClick={(event) => { event.stopPropagation(); setOpen(true); }}>Delete</button>}
    {open && createPortal(<div data-modal-layer className='fixed inset-0 z-[150] isolate flex items-center justify-center bg-black/70 p-4'
      onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
      <section role='dialog' aria-modal='true' aria-labelledby={`delete-${transactionId}`}
        className='w-full max-w-md space-y-4 rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-5'>
        <h2 id={`delete-${transactionId}`} className='font-semibold text-[var(--text-primary)]'>Delete transaction?</h2>
        <p className='text-sm text-[var(--text-secondary)]'>The account balance will be reversed and the transaction will disappear from your list.
          {eligibility?.kind === 'split_expense' ? ' Its linked split will also be hidden.' : ''}</p>
        {error && <p role='alert' className='text-sm text-red-500'>{error}</p>}
        <div className='flex justify-end gap-3'>
          {!isLoading ? <button type='button' onClick={() => setOpen(false)}>Cancel</button> : null}
          <button type='button' disabled={isLoading} className='rounded-lg bg-red-600 px-4 py-2 font-semibold text-white'
            onClick={() => { void remove(transactionId).unwrap().then(() => {
              setOpen(false); setDeleted(true); onDeleted?.();
            }).catch(() => setError('Could not delete this transaction. Please try again.')); }}>
            {isLoading ? 'Deleting…' : 'Delete transaction'}</button>
        </div>
      </section>
    </div>, document.body)}
  </>;
}

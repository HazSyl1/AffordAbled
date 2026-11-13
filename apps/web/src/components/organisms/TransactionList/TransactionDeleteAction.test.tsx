// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TransactionDeleteAction } from './TransactionDeleteAction';

const mocks = vi.hoisted(() => ({
  isLoading: false,
  remove: vi.fn(),
  unwrap: vi.fn(),
}));

vi.mock('../../../features/transactions/transactionsApi', () => ({
  useGetTransactionDeletionStatusQuery: () => ({ data: { can_delete: true, kind: 'standard' } }),
  useDeleteTransactionMutation: () => [mocks.remove, { isLoading: mocks.isLoading }],
}));

describe('TransactionDeleteAction', () => {
  afterEach(cleanup);

  beforeEach(() => {
    mocks.isLoading = false;
    mocks.remove.mockReset();
    mocks.unwrap.mockReset();
    mocks.remove.mockReturnValue({ unwrap: mocks.unwrap });
  });

  it('removes Cancel while the transaction is being deleted', () => {
    const { rerender } = render(<TransactionDeleteAction transactionId='transaction-1' />);
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(screen.getByRole('button', { name: 'Cancel' })).toBeVisible();
    mocks.isLoading = true;
    rerender(<TransactionDeleteAction transactionId='transaction-1' />);

    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Deleting…' })).toBeDisabled();
  });
});

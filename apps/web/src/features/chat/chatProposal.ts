import type { CreateTransactionFormValues } from '../../components/organisms/CreateTransactionForm/CreateTransactionForm.schema';
import type { ChatTransactionProposal } from './chatApi';

function toLocalDateTimeInput(value: string): string {
  const parsedDate = new Date(value);
  if (Number.isNaN(parsedDate.getTime())) {
    return '';
  }

  const localTimestamp = new Date(parsedDate.getTime() - parsedDate.getTimezoneOffset() * 60 * 1000);
  return localTimestamp.toISOString().slice(0, 16);
}

export function mapProposalToCreateTransactionValues(
  proposal: ChatTransactionProposal,
): Partial<CreateTransactionFormValues> {
  return {
    accountId: proposal.account_id,
    type: proposal.type,
    amountRupees: (proposal.amount_paise / 100).toFixed(2),
    occurredAt: toLocalDateTimeInput(proposal.occurred_at),
    categoryId: proposal.category_id,
    merchant: proposal.merchant ?? '',
    note: proposal.note ?? '',
  };
}

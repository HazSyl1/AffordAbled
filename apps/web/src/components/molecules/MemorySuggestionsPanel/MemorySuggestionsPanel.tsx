import { Check, Lightbulb, X } from 'lucide-react';

import { Button } from '../../atoms/Button';
import { Card } from '../../atoms/Card';
import { useListAccountsQuery } from '../../../features/accounts/accountsApi';
import { useListCategoriesQuery } from '../../../features/categories/categoriesApi';
import {
  useConfirmMemorySuggestionMutation,
  useDismissMemorySuggestionMutation,
  type MemorySuggestion,
} from '../../../features/memory/memoryApi';
import { suggestionDescription } from '../../../features/memory/memoryText';

interface MemorySuggestionsPanelProps {
  suggestions: MemorySuggestion[];
  compact?: boolean;
}

export function MemorySuggestionsPanel({ suggestions, compact = false }: MemorySuggestionsPanelProps) {
  const [confirm, { isLoading: confirming }] = useConfirmMemorySuggestionMutation();
  const [dismiss, { isLoading: dismissing }] = useDismissMemorySuggestionMutation();
  const { data: categories = [] } = useListCategoriesQuery();
  const { data: accounts = [] } = useListAccountsQuery();
  const categoryNames = new Map(categories.map((category) => [category.id, category.name]));
  const accountNames = new Map(accounts.map((account) => [account.id, account.name]));

  if (!suggestions.length) {
    return null;
  }

  return (
    <Card className={compact ? 'border-[color:rgba(168,85,247,0.35)] p-4' : 'border-[color:rgba(168,85,247,0.35)] p-5'}>
      <div className='flex items-start gap-3'>
        <Lightbulb className='mt-0.5 h-5 w-5 shrink-0 text-[var(--brand-primary)]' aria-hidden='true' />
        <div className='min-w-0 flex-1'>
          <h3 className='font-semibold text-[var(--text-primary)]'>A few patterns I noticed</h3>
          <p className='mt-1 text-xs text-[var(--text-muted)]'>Confirm to use a pattern in future suggestions. Existing transactions and splits will not change.</p>
          <div className='mt-3 space-y-3'>
            {suggestions.map((suggestion) => (
              <div key={suggestion.id} className='rounded-xl border border-[var(--bg-border)] bg-[var(--bg-elevated)] p-3'>
                <p className='text-sm text-[var(--text-secondary)]'>{suggestionDescription(suggestion, categoryNames, accountNames)}</p>
                <div className='mt-3 flex gap-2'>
                  <Button type='button' aria-label='Confirm suggestion' title='Confirm suggestion' className='min-h-9 w-10 px-2 py-2 text-xs' isLoading={confirming} onClick={() => { void confirm(suggestion.id); }}>
                    <Check className='h-4 w-4' aria-hidden='true' />{compact ? null : ' Use this'}
                  </Button>
                  <Button type='button' variant='secondary' aria-label='Dismiss suggestion' title='Dismiss suggestion' className='min-h-9 w-10 px-2 py-2 text-xs' isLoading={dismissing} onClick={() => { void dismiss(suggestion.id); }}>
                    <X className='h-4 w-4' aria-hidden='true' />{compact ? null : ' Dismiss'}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

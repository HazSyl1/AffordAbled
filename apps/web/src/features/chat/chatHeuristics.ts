export function didAssistantLikelyAddTransaction(message: string): boolean {
  const normalized = message.toLowerCase();

  const hasActionVerb = /(logged|recorded|added|saved)/.test(normalized);
  const hasTransactionContext = /(transaction|expense|income|transfer|refund)/.test(normalized);
  const hasNegativePattern = /(cannot|can't|could not|couldn't|unable|not\s+(logged|recorded|added|saved))/.test(normalized);

  return hasActionVerb && hasTransactionContext && !hasNegativePattern;
}

import type { MemorySuggestion } from './memoryApi';

export function describeMemory(
  memory: MemorySuggestion,
  categoryNames: Map<string, string>,
  accountNames: Map<string, string>,
): string {
  const subject = (memory.subject_key.trim() || 'this item').replace(/\b\w/g, (letter) => letter.toUpperCase());
  const value = memory.value;

  if (memory.memory_type === 'category_mapping' && typeof value.category_id === 'string') {
    return `You often classify ${subject} as ${categoryNames.get(value.category_id) ?? 'a saved category'}.`;
  }

  if (memory.memory_type === 'account_mapping' && typeof value.account_id === 'string') {
    return `You often use ${accountNames.get(value.account_id) ?? 'the same account'} for ${subject}.`;
  }

  if (memory.memory_type === 'split_method') {
    const mode = value.mode === 'equal' ? 'split expenses equally' : 'use custom splits';
    const ratioValue = value.share_ratio;
    const ratio = typeof ratioValue === 'number' && Number.isFinite(ratioValue)
      ? ` ${subject}'s share was about ${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(ratioValue * 100)}% of the total.`
      : '';
    return `You often ${mode} with ${subject}.${ratio}`;
  }

  if (memory.memory_type === 'user_preference' || memory.memory_type === 'split_person_preference') {
    const key = typeof value.key === 'string' ? value.key.replaceAll('_', ' ') : 'preference';
    const preference = typeof value.value === 'string' ? value.value : 'a saved preference';
    return memory.memory_type === 'user_preference'
      ? `You prefer ${key}: ${preference}.`
      : `${subject}'s ${key} preference is ${preference}.`;
  }

  return `You have a recurring ${memory.memory_type.replaceAll('_', ' ')} preference for ${subject}.`;
}

export function suggestionDescription(
  memory: MemorySuggestion,
  categoryNames: Map<string, string>,
  accountNames: Map<string, string>,
): string {
  if (memory.memory_type === 'split_method') {
    const evidence = `${memory.evidence_count} reviewed split${memory.evidence_count === 1 ? '' : 's'}`;
    const description = describeMemory(memory, categoryNames, accountNames);
    const lowerDescription = description.charAt(0).toLowerCase() + description.slice(1);
    return `Across ${evidence}, ${lowerDescription} Is this a pattern you want me to remember?`;
  }
  return `${describeMemory(memory, categoryNames, accountNames)} Should I remember this for future suggestions?`;
}

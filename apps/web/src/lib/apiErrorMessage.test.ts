import { describe, expect, it } from 'vitest';

import { apiErrorMessage } from './apiErrorMessage';

describe('apiErrorMessage', () => {
  it('reads FastAPI string and structured details', () => {
    expect(apiErrorMessage({ data: { detail: 'Invalid image' } }, 'Fallback')).toBe('Invalid image');
    expect(apiErrorMessage({ data: { detail: { message: 'Daily upload limit reached' } } }, 'Fallback'))
      .toBe('Daily upload limit reached');
  });

  it('falls back when no useful message is present', () => {
    expect(apiErrorMessage({ data: {} }, 'Fallback')).toBe('Fallback');
  });
});

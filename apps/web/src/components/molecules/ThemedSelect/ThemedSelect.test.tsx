import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ThemedSelect } from './ThemedSelect';

describe('ThemedSelect search', () => {
  it('filters people and selects the matching result', () => {
    const onChange = vi.fn();
    render(<ThemedSelect id='person' value='' placeholder='Choose a person' searchable
      searchPlaceholder='Search saved people'
      options={[
        { value: 'Isha', label: 'Isha' },
        { value: 'Sudhansu', label: 'Sudhansu' },
        { value: 'Ravi', label: 'Ravi' },
      ]} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: 'Choose a person' }));
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved people' }), {
      target: { value: 'sudh' },
    });

    expect(screen.queryByRole('option', { name: 'Isha' })).toBeNull();
    fireEvent.click(screen.getByRole('option', { name: 'Sudhansu' }));
    expect(onChange).toHaveBeenCalledWith('Sudhansu');
  });
});

import { ChevronDown } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

export interface ThemedSelectOption {
  label: string;
  value: string;
  disabled?: boolean;
}

export interface ThemedSelectProps {
  id: string;
  value: string;
  placeholder: string;
  options: ThemedSelectOption[];
  onChange: (nextValue: string) => void;
  invalid?: boolean;
}

const SELECT_TRIGGER_CLASS =
  'flex w-full min-h-12 items-center justify-between rounded-xl border border-[var(--bg-border)] bg-[var(--bg-surface)] px-3 py-3 text-left text-base text-[var(--text-primary)] shadow-sm outline-none transition-colors focus-visible:border-[var(--brand-primary)] focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]';

export function ThemedSelect({ id, value, placeholder, options, onChange, invalid = false }: ThemedSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, []);

  const selectedOption = options.find((option) => option.value === value);

  return <div className='relative' ref={rootRef}>
    <button
      id={id}
      type='button'
      aria-haspopup='listbox'
      aria-expanded={isOpen}
      aria-invalid={invalid || undefined}
      className={`${SELECT_TRIGGER_CLASS} ${invalid ? 'border-red-500 bg-red-500/10' : ''}`}
      onClick={() => setIsOpen((open) => !open)}
      onKeyDown={(event) => {
        if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          setIsOpen(true);
        }
        if (event.key === 'Escape') setIsOpen(false);
      }}
    >
      <span className={selectedOption ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}>
        {selectedOption?.label ?? placeholder}
      </span>
      <ChevronDown className={[
        'pointer-events-none size-4 text-[var(--text-muted)] transition-transform duration-200',
        isOpen ? 'rotate-180' : '',
      ].join(' ')} />
    </button>
    {isOpen && <div className='absolute left-0 right-0 top-[calc(100%+0.5rem)] z-30 overflow-hidden rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] shadow-[0_20px_48px_rgba(0,0,0,0.34)]'>
      <ul role='listbox' aria-labelledby={id} className='max-h-64 overflow-auto p-1'>
        {options.map((option) => <li key={option.value}>
          <button
            type='button'
            role='option'
            aria-selected={option.value === value}
            disabled={option.disabled}
            className={[
              'w-full rounded-lg px-3 py-2 text-left text-sm transition-all',
              option.disabled
                ? 'cursor-not-allowed text-[var(--text-muted)]'
                : option.value === value
                  ? 'bg-[var(--bg-border)] font-medium text-[var(--text-primary)] shadow-[inset_0_0_0_1px_var(--bg-border)]'
                  : 'text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] hover:shadow-[inset_0_0_0_1px_var(--bg-border)]',
            ].join(' ')}
            onClick={() => {
              if (option.disabled) return;
              onChange(option.value);
              setIsOpen(false);
            }}
          >{option.label}</button>
        </li>)}
      </ul>
    </div>}
  </div>;
}

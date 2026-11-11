import { Camera, Keyboard, MessageCircle, Mic } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { BottomSheet } from '../../molecules/BottomSheet';

interface CreateLauncherProps {
  isOpen: boolean;
  onClose: () => void;
}

const MODES = [
  { label: 'Enter manually', description: 'Add an expense, income, refund, or transfer.', icon: Keyboard, destination: '/transactions?create=manual' },
  { label: 'Tell the assistant', description: 'Describe what happened in your own words.', icon: MessageCircle, destination: '/chat?compose=1' },
  { label: 'Use your voice', description: 'Speak naturally and review what was heard.', icon: Mic, destination: '/chat?voice=1' },
  { label: 'Scan a receipt', description: 'Upload a receipt and check the extracted details.', icon: Camera, destination: '/chat?receipt=1' },
] as const;

export function CreateLauncher({ isOpen, onClose }: CreateLauncherProps) {
  const navigate = useNavigate();

  return (
    <BottomSheet isOpen={isOpen} onClose={onClose} title='Add to your wallet'>
      <p className='mb-4 max-w-lg text-sm leading-6 text-[var(--ink-muted)]'>
        Choose the quickest starting point. Nothing is saved until you review the details.
      </p>
      <div className='grid gap-2 sm:grid-cols-2'>
        {MODES.map(({ label, description, icon: Icon, destination }) => (
          <button
            key={label}
            type='button'
            className='group flex min-h-24 items-start gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left transition-[background-color,border-color,transform] duration-150 ease-[var(--ease-out)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-subtle)] active:scale-[0.99]'
            onClick={() => {
              onClose();
              navigate(destination);
            }}
          >
            <span className='flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]'>
              <Icon className='h-5 w-5' strokeWidth={2} aria-hidden='true' />
            </span>
            <span>
              <span className='block text-sm font-semibold text-[var(--ink)]'>{label}</span>
              <span className='mt-1 block text-xs leading-5 text-[var(--ink-muted)]'>{description}</span>
            </span>
          </button>
        ))}
      </div>
    </BottomSheet>
  );
}


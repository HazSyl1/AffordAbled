import { useEffect, useState } from 'react';
import { CheckCircle2 } from 'lucide-react';

import { Button } from '../../atoms/Button';
import { Card } from '../../atoms/Card';

interface TransactionSuccessOverlayProps {
  message: string;
  expiresAt: number;
  onClose: () => void;
  onContinue: () => void;
}

export function TransactionSuccessOverlay({ message, expiresAt, onClose, onContinue }: TransactionSuccessOverlayProps) {
  const [secondsRemaining, setSecondsRemaining] = useState(() => Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000)));

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsRemaining(Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000)));
    }, 250);
    return () => window.clearInterval(timer);
  }, [expiresAt]);

  return (
    <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4' role='dialog' aria-modal='true' aria-labelledby='task-success-title'>
      <Card className='w-full max-w-md border-[var(--brand-primary)] p-6 text-center shadow-2xl'>
        <CheckCircle2 className='mx-auto h-12 w-12 text-[var(--positive)]' aria-hidden='true' />
        <h2 id='task-success-title' className='mt-3 text-lg font-bold text-[var(--text-primary)]'>Tasks completed</h2>
        <p className='mt-2 whitespace-pre-line text-sm text-[var(--text-secondary)]'>{message}</p>
        <p className='mt-4 text-sm text-[var(--text-muted)]'>Going to your dashboard in {secondsRemaining} seconds.</p>
        <div className='mt-5 flex flex-col gap-3 sm:flex-row'>
          <Button type='button' variant='secondary' onClick={onClose}>Close</Button>
          <Button type='button' autoFocus onClick={onContinue}>Continue chatting</Button>
        </div>
      </Card>
    </div>
  );
}

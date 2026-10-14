import { Mic } from 'lucide-react';

interface VoiceCaptureModalProps {
  cancelLabel: string;
  elapsedSeconds: number;
  isOpen: boolean;
  isProcessing: boolean;
  onCancel: () => void;
  onStop: () => void;
  processingLabel: string;
  recordingLabel: string;
  stopLabel: string;
  title: string;
}

function formatElapsedSeconds(value: number): string {
  const minutes = Math.floor(value / 60)
    .toString()
    .padStart(2, '0');
  const seconds = Math.floor(value % 60)
    .toString()
    .padStart(2, '0');
  return `${minutes}:${seconds}`;
}

export function VoiceCaptureModal({
  cancelLabel,
  elapsedSeconds,
  isOpen,
  isProcessing,
  onCancel,
  onStop,
  processingLabel,
  recordingLabel,
  stopLabel,
  title,
}: VoiceCaptureModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className='pointer-events-none fixed inset-x-0 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-[90] flex justify-center px-4'>
      <div className='pointer-events-auto w-full max-w-md rounded-2xl border border-[var(--bg-border)] bg-[color:rgba(15,15,17,0.96)] px-4 py-3 shadow-[0_16px_45px_rgba(0,0,0,0.45)] backdrop-blur-xl'>
        <p className='sr-only'>{title}</p>

        <div className='flex items-center gap-3'>
          {isProcessing ? (
            <span
              className='inline-flex h-6 w-6 shrink-0 animate-spin rounded-full border-2 border-[var(--bg-border)] border-t-[var(--brand-primary)]'
              aria-hidden='true'
            />
          ) : (
            <span className='relative inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--brand-primary)]/25 text-[var(--brand-primary)]'>
              <span className='absolute h-7 w-7 rounded-full bg-[var(--brand-primary)]/30 animate-ping' aria-hidden='true' />
              <Mic className='relative h-3.5 w-3.5' strokeWidth={2.4} aria-hidden='true' />
            </span>
          )}

          <div className='min-w-0 flex-1'>
            <p className='truncate text-sm font-semibold text-[var(--text-primary)]'>{isProcessing ? processingLabel : recordingLabel}</p>
            <p className='mt-0.5 text-xs font-semibold tabular-nums text-[var(--text-secondary)]'>
              {isProcessing ? '--:--' : formatElapsedSeconds(elapsedSeconds)}
            </p>
          </div>

          {!isProcessing ? (
            <>
              <button
                type='button'
                className='inline-flex h-9 items-center justify-center rounded-lg border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-3 text-xs font-semibold text-[var(--text-primary)] transition-colors hover:bg-[var(--bg-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'
                onClick={onCancel}
              >
                {cancelLabel}
              </button>
              <button
                type='button'
                className='inline-flex h-9 items-center justify-center rounded-lg bg-[var(--negative)] px-3 text-xs font-semibold text-white transition-colors hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--negative)]'
                onClick={onStop}
              >
                {stopLabel}
              </button>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

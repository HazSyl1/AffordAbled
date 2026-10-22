import { APP_NAME } from '../../../constants';

export function PageLoader() {
  return (
    <main
      role='status'
      aria-live='polite'
      className='relative flex min-h-[100dvh] items-center justify-center overflow-hidden bg-[var(--bg-app)] px-6'
    >
      <div
        className='pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,rgba(168,85,247,0.16),transparent_50%)]'
        aria-hidden='true'
      />
      <div className='relative flex flex-col items-center text-center'>
        <img
          src='/affordabled-wallet-loader.svg'
          alt=''
          aria-hidden='true'
          width='360'
          height='280'
          className='h-auto w-56 max-w-full sm:w-72'
        />
        <p className='mt-1 text-xs font-bold uppercase tracking-[0.24em] text-[var(--brand-primary)]'>
          {APP_NAME}
        </p>
        <p className='mt-3 text-sm text-[var(--text-secondary)]'>Getting your wallet ready…</p>
      </div>
    </main>
  );
}

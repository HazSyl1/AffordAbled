import { Card } from '../../components/atoms/Card';

export function ProfilePage() {
  return (
    <div className='mx-auto w-full max-w-[900px] px-4 py-4 md:px-6 md:py-6'>
      <Card className='p-6 text-center'>
        <p className='mb-2 text-3xl'>👤</p>
        <h1 className='text-lg font-semibold text-[var(--text-primary)]'>Profile</h1>
        <p className='mt-1 text-sm text-[var(--text-muted)]'>Profile settings UI is coming soon.</p>
      </Card>
    </div>
  );
}

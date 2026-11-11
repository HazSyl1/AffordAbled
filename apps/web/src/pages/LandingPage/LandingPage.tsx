import { ArrowRight, Camera, Check, ChevronRight, Keyboard, MessageCircle, Mic, ShieldCheck, Users } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { BrandMark } from '../../components/atoms/BrandMark';
import { ThemeControl } from '../../components/molecules/ThemeControl';

const captureModes = [
  { id: 'manual', label: 'Manual', icon: Keyboard, input: 'Dinner with the team', amount: '₹2,480.00', note: 'Food & dining · HDFC card' },
  { id: 'chat', label: 'Chat', icon: MessageCircle, input: 'Spent 2480 on dinner with the team', amount: '₹2,480.00', note: 'Assistant found: expense · tonight' },
  { id: 'voice', label: 'Voice', icon: Mic, input: 'Dinner was two thousand four hundred and eighty', amount: '₹2,480.00', note: 'Voice transcript ready to review' },
  { id: 'receipt', label: 'Receipt', icon: Camera, input: 'Receipt from Bombay Canteen', amount: '₹2,480.00', note: 'Merchant and total extracted' },
] as const;

export function LandingPage() {
  const [captureMode, setCaptureMode] = useState<(typeof captureModes)[number]['id']>('chat');
  const activeMode = captureModes.find((mode) => mode.id === captureMode) ?? captureModes[0];

  return (
    <div className='min-h-screen bg-[var(--canvas)] text-[var(--ink)]'>
      <header className='fixed inset-x-0 top-0 z-50 border-b border-[var(--border)] bg-[var(--canvas)]/95'>
        <div className='mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8'>
          <Link to='/' className='inline-flex items-center gap-2.5 rounded-lg'>
            <span className='flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--brand-panel)] text-[var(--brand-panel-ink)]'>
              <BrandMark className='h-6 w-6' />
            </span>
            <span className='hidden text-sm font-bold tracking-[-0.02em] sm:inline'>AffordAbled</span>
          </Link>
          <nav className='flex items-center gap-1' aria-label='Public navigation'>
            <span className='hidden sm:block'><ThemeControl compact /></span>
            <Link to='/login' className='hidden min-h-11 items-center rounded-lg px-3 text-sm font-medium text-[var(--ink-secondary)] hover:text-[var(--ink)] sm:inline-flex'>Log in</Link>
            <Link to='/register' className='inline-flex min-h-11 items-center rounded-[var(--btn-radius)] bg-[var(--accent)] px-4 text-sm font-semibold text-[var(--on-accent)] transition-colors hover:bg-[var(--accent-hover)]'><span className='sm:hidden'>Get started</span><span className='hidden sm:inline'>Create your wallet</span></Link>
          </nav>
        </div>
      </header>

      <main>
        <section className='flex min-h-[100svh] items-center pt-24'>
          <div className='mx-auto grid w-full min-w-0 max-w-7xl gap-12 px-4 py-16 sm:px-6 lg:grid-cols-[0.85fr_1.15fr] lg:items-center lg:px-8'>
            <div className='min-w-0 max-w-2xl' style={{ animation: 'enter-soft 500ms var(--ease-out) both' }}>
              <h1 className='text-balance text-[clamp(2.8rem,6vw,5.6rem)] font-semibold leading-[0.96] tracking-[-0.04em]'>Know where your money stands before you act.</h1>
              <p className='mt-7 max-w-xl text-lg leading-8 text-[var(--ink-secondary)]'>AffordAbled brings accounts, transactions, shared expenses, and AI-assisted capture into one wallet you stay in control of.</p>
              <div className='mt-8 flex flex-col gap-3 sm:flex-row'>
                <Link to='/register' className='inline-flex min-h-12 items-center justify-center gap-2 rounded-[var(--btn-radius)] bg-[var(--accent)] px-5 text-sm font-semibold text-[var(--on-accent)] transition-[background-color,transform] hover:bg-[var(--accent-hover)] active:scale-[0.98]'>Create your wallet <ArrowRight className='h-4 w-4' aria-hidden='true' /></Link>
                <a href='#capture' className='inline-flex min-h-12 items-center justify-center gap-2 rounded-[var(--btn-radius)] border border-[var(--border)] bg-[var(--surface)] px-5 text-sm font-semibold text-[var(--ink)] transition-colors hover:bg-[var(--surface-subtle)]'>See how review works</a>
              </div>
              <p className='mt-5 text-sm text-[var(--ink-muted)]'>Nothing is saved until you review the details.</p>
            </div>

            <div className='relative mx-auto w-full min-w-0 max-w-3xl overflow-hidden' aria-label='Illustrative AffordAbled workspace'>
              <div className='min-w-0 overflow-hidden rounded-2xl bg-[var(--brand-panel)] p-3 shadow-[var(--shadow-raised)] sm:p-4'>
                <div className='flex items-center justify-between border-b border-[var(--brand-panel-border)] px-2 pb-3 text-[var(--brand-panel-ink)]'>
                  <span className='text-sm font-semibold'>Good evening, Aanya</span>
                  <span className='rounded-full bg-[var(--brand-panel-active)] px-2.5 py-1 text-xs'>Illustrative workspace</span>
                </div>
                <div className='grid gap-3 pt-3 md:grid-cols-[1.05fr_0.95fr]'>
                  <div className='rounded-xl bg-white p-5 text-[#1f2937] shadow-[0_8px_18px_rgb(15_23_42_/_14%)]'>
                    <p className='text-sm text-[#4b5563]'>Across your wallet</p>
                    <p className='money mt-2 text-4xl font-semibold tracking-[-0.03em]'>₹1,24,680</p>
                    <div className='mt-7 grid grid-cols-2 gap-4 border-t border-[#d1d9e6] pt-4'>
                      <div><p className='text-xs text-[#4b5563]'>Income this month</p><p className='money mt-1 font-semibold'>₹72,000</p></div>
                      <div><p className='text-xs text-[#4b5563]'>Spent this month</p><p className='money mt-1 font-semibold'>₹31,420</p></div>
                    </div>
                  </div>
                  <div className='rounded-xl bg-[#e8eef6] p-4 text-[#1f2937] shadow-[inset_-3px_-3px_7px_#ffffff,inset_3px_3px_7px_#d1d9e6]'>
                    <div className='flex items-center justify-between'><p className='text-sm font-semibold'>Recent activity</p><span className='text-xs text-[#4b5563]'>Today</span></div>
                    {[['Bombay Canteen', '−₹2,480'], ['Metro recharge', '−₹500'], ['Project payment', '+₹18,000']].map(([name, amount]) => (
                      <div key={name} className='mt-3 flex items-center justify-between border-b border-[#d1d9e6] pb-3 last:border-0 last:pb-0'>
                        <span className='text-sm'>{name}</span><span className='money text-sm font-semibold'>{amount}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id='capture' className='flex min-h-[100svh] items-center border-t border-[var(--border)] bg-[var(--surface)]'>
          <div className='mx-auto grid w-full max-w-7xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[0.8fr_1.2fr] lg:items-center lg:px-8'>
            <div className='max-w-xl'>
              <h2 className='text-4xl font-semibold leading-tight tracking-[-0.035em] sm:text-5xl'>Four ways in. One review before anything changes.</h2>
              <p className='mt-5 text-lg leading-8 text-[var(--ink-secondary)]'>Type the details yourself, describe them in chat, speak naturally, or use a receipt. Every path ends at the same clear checkpoint.</p>
              <ul className='mt-7 space-y-3 text-sm text-[var(--ink-secondary)]'>
                {['See the amount and account', 'Correct the category or date', 'Confirm the exact action'].map((item) => <li key={item} className='flex items-center gap-3'><Check className='h-5 w-5 text-[var(--accent)]' aria-hidden='true' />{item}</li>)}
              </ul>
            </div>
            <div className='rounded-2xl border border-[var(--border)] bg-[var(--canvas)] p-3 sm:p-5'>
              <div className='grid grid-cols-4 gap-1 rounded-xl bg-[var(--surface-subtle)] p-1' role='tablist' aria-label='Capture methods'>
                {captureModes.map(({ id, label, icon: Icon }) => <button key={id} type='button' role='tab' aria-selected={captureMode === id} className={['inline-flex min-h-12 items-center justify-center gap-2 rounded-lg px-2 text-xs font-medium transition-[background-color,color,box-shadow] sm:text-sm', captureMode === id ? 'bg-[var(--surface)] text-[var(--ink)] shadow-[var(--shadow-soft)]' : 'text-[var(--ink-muted)]'].join(' ')} onClick={() => setCaptureMode(id)}><Icon className='h-4 w-4' aria-hidden='true' /><span className='hidden sm:inline'>{label}</span></button>)}
              </div>
              <div className='mt-4 rounded-xl bg-[var(--surface)] p-5'>
                <p className='text-sm text-[var(--ink-muted)]'>{activeMode.input}</p>
                <div className='my-5 h-px bg-[var(--border)]' />
                <div className='flex items-end justify-between gap-4'>
                  <div><p className='text-sm font-medium text-[var(--ink-secondary)]'>Review transaction</p><p className='mt-1 text-xs text-[var(--ink-muted)]'>{activeMode.note}</p></div>
                  <p className='money shrink-0 text-2xl font-semibold tracking-[-0.025em]'>{activeMode.amount}</p>
                </div>
                <button type='button' className='mt-6 inline-flex min-h-11 w-full items-center justify-center rounded-[var(--btn-radius)] bg-[var(--accent)] px-4 text-sm font-semibold text-[var(--on-accent)]'>Confirm and add</button>
              </div>
            </div>
          </div>
        </section>

        <section className='flex min-h-[100svh] items-center border-t border-[var(--border)]'>
          <div className='mx-auto grid w-full max-w-7xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-2 lg:items-center lg:px-8'>
            <div className='order-2 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] lg:order-1'>
              <div className='flex items-center justify-between border-b border-[var(--border)] p-5'><div><p className='font-semibold'>Goa weekend</p><p className='mt-1 text-sm text-[var(--ink-muted)]'>4 people · 6 expenses</p></div><Users className='h-5 w-5 text-[var(--accent)]' aria-hidden='true' /></div>
              {[['Isha pays Aanya', '₹1,840'], ['Piyush pays Dev', '₹960'], ['Dev pays Aanya', '₹425']].map(([transfer, amount], index) => <div key={transfer} className='flex items-center justify-between border-b border-[var(--border)] p-5 last:border-0'><div className='flex items-center gap-3'><span className='flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent-soft)] text-xs font-semibold text-[var(--accent)]'>{index + 1}</span><span className='text-sm'>{transfer}</span></div><span className='money font-semibold'>{amount}</span></div>)}
              <div className='bg-[var(--surface-subtle)] p-4 text-sm text-[var(--ink-secondary)]'>Coupons, fees, tips, and multiple payers are already included in this preview.</div>
            </div>
            <div className='order-1 max-w-xl lg:order-2'>
              <h2 className='text-4xl font-semibold leading-tight tracking-[-0.035em] sm:text-5xl'>Shared money without the awkward arithmetic.</h2>
              <p className='mt-5 text-lg leading-8 text-[var(--ink-secondary)]'>Split individual items, combine several bills, account for coupons and fees, and see the smallest set of transfers before anything touches your wallet.</p>
              <Link to='/register' className='mt-7 inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-[var(--accent)]'>Start a clear settlement <ChevronRight className='h-4 w-4' aria-hidden='true' /></Link>
            </div>
          </div>
        </section>

        <section className='flex min-h-[80svh] items-center border-t border-[var(--border)] bg-[var(--brand-panel)] text-[var(--brand-panel-ink)]'>
          <div className='mx-auto grid w-full max-w-7xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[0.8fr_1.2fr] lg:items-center lg:px-8'>
            <div>
              <ShieldCheck className='h-8 w-8 text-[var(--accent)]' aria-hidden='true' />
              <h2 className='mt-6 text-4xl font-semibold leading-tight tracking-[-0.035em] sm:text-5xl'>The assistant can help. You keep the final say.</h2>
            </div>
            <div className='divide-y divide-[var(--brand-panel-border)] border-y border-[var(--brand-panel-border)]'>
              {[
                ['Review before save', 'AI-created transactions stop at a confirmation step.'],
                ['Memories by consent', 'Suggested preferences guide future assistance only after you approve them.'],
                ['Visible consequences', 'Transfers, repayments, and settlements explain what changes in your wallet.'],
              ].map(([title, body]) => <div key={title} className='grid gap-2 py-6 sm:grid-cols-[0.7fr_1.3fr]'><p className='font-semibold'>{title}</p><p className='text-[var(--brand-panel-ink)]/65'>{body}</p></div>)}
            </div>
          </div>
        </section>

        <section className='flex min-h-[70svh] items-center border-t border-[var(--border)]'>
          <div className='mx-auto w-full max-w-4xl px-4 py-24 text-center sm:px-6'>
            <h2 className='text-balance text-4xl font-semibold tracking-[-0.035em] sm:text-6xl'>Make everyday money easier to understand.</h2>
            <p className='mx-auto mt-5 max-w-2xl text-lg leading-8 text-[var(--ink-secondary)]'>Start with one account. Add money your way. Review every important change.</p>
            <Link to='/register' className='mt-8 inline-flex min-h-12 items-center justify-center gap-2 rounded-[var(--btn-radius)] bg-[var(--accent)] px-6 text-sm font-semibold text-[var(--on-accent)] transition-colors hover:bg-[var(--accent-hover)]'>Create your wallet <ArrowRight className='h-4 w-4' aria-hidden='true' /></Link>
          </div>
        </section>
      </main>

      <footer className='border-t border-[var(--border)]'>
        <div className='mx-auto flex max-w-7xl flex-col gap-3 px-4 py-8 text-sm text-[var(--ink-muted)] sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8'>
          <p>© {new Date().getFullYear()} AffordAbled</p>
          <div className='flex gap-5'><Link to='/login'>Log in</Link><Link to='/register'>Create account</Link></div>
        </div>
      </footer>
    </div>
  );
}

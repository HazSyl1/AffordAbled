import { ArrowDown, ArrowRight, Bot, Camera, Check, CircleHelp, Mail, Mic, ShieldCheck, Split, Wallet } from 'lucide-react';
import { Link } from 'react-router-dom';

import { APP_NAME } from '../../constants';

const features = [
  {
    icon: Bot,
    title: 'Talk it through',
    description: 'Ask questions about your money or describe a transaction in everyday language.',
  },
  {
    icon: Camera,
    title: 'Capture the details',
    description: 'Use a receipt image or voice note to start recording an expense. Review details before they are saved.',
  },
  {
    icon: Split,
    title: 'Make shared costs clearer',
    description: 'Split an expense between people, see what is owed, and mark a share as repaid.',
  },
  {
    icon: ShieldCheck,
    title: 'Keep your preferences yours',
    description: 'Review suggested preferences and choose what the assistant should remember for future suggestions.',
  },
];

const steps = [
  ['Add your accounts', 'Set up the accounts and categories you use to organize your money.'],
  ['Tell AffordAbled what happened', 'Use chat, voice, or a receipt image to describe an income or expense.'],
  ['Review and understand', 'Check your transactions, explore summaries, and keep shared expenses in view.'],
];

export function LandingPage() {
  return (
    <main className='min-h-screen overflow-hidden text-[var(--text-primary)]'>
      <header className='mx-auto flex w-full max-w-7xl items-center justify-between px-5 py-5 sm:px-8 lg:px-10'>
        <Link to='/' className='inline-flex items-center gap-3 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'>
          <span className='flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--brand-primary)] text-white shadow-lg shadow-purple-950/40'>
            <Wallet className='h-5 w-5' aria-hidden='true' />
          </span>
          <span>
            <span className='block text-sm font-bold tracking-[0.12em]'>{APP_NAME}</span>
            <span className='block text-xs text-[var(--text-muted)]'>Your personal AI wallet</span>
          </span>
        </Link>
        <nav aria-label='Main navigation' className='flex items-center gap-2 sm:gap-3'>
          <a href='#how-it-works' className='hidden rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-white sm:inline-flex'>How it works</a>
          <a href='#help' className='hidden rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-white sm:inline-flex'>Help</a>
          <Link to='/login' className='rounded-xl px-3 py-2 text-sm font-semibold text-[var(--text-secondary)] transition-colors hover:bg-white/5 hover:text-white'>Log in</Link>
          <Link to='/register' className='inline-flex items-center gap-2 rounded-xl bg-[var(--brand-primary)] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-hover)]'>Get started <ArrowRight className='h-4 w-4' aria-hidden='true' /></Link>
        </nav>
      </header>

      <section className='relative mx-auto grid w-full max-w-7xl items-center gap-12 px-5 pb-20 pt-12 sm:px-8 sm:pt-16 lg:grid-cols-[1fr_0.9fr] lg:px-10 lg:pb-28 lg:pt-20'>
        <div className='absolute -left-40 top-0 -z-10 h-[28rem] w-[28rem] rounded-full bg-purple-500/10 blur-3xl' aria-hidden='true' />
        <div className='max-w-2xl'>
          <div className='mb-6 inline-flex items-center gap-2 rounded-full border border-[var(--brand-primary)]/30 bg-[var(--brand-primary)]/10 px-3 py-1.5 text-xs font-semibold text-purple-200'>
            <span className='h-2 w-2 rounded-full bg-[var(--brand-primary)]' aria-hidden='true' /> Everyday money, easier to follow
          </div>
          <h1 className='text-4xl font-bold leading-[1.08] tracking-tight sm:text-5xl lg:text-6xl'>Your money has a lot to say. <span className='text-purple-300'>Let’s make it make sense.</span></h1>
          <p className='mt-6 max-w-xl text-base leading-7 text-[var(--text-secondary)] sm:text-lg'>AffordAbled brings transactions, account balances, spending questions, and shared expenses into one personal finance workspace—with an AI assistant that can work from the way you naturally describe things.</p>
          <div className='mt-8 flex flex-col gap-3 sm:flex-row'>
            <Link to='/register' className='inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[var(--brand-primary)] px-5 text-sm font-semibold text-white shadow-lg shadow-purple-950/30 transition-all hover:-translate-y-0.5 hover:bg-[var(--brand-hover)]'>Create your account <ArrowRight className='h-4 w-4' aria-hidden='true' /></Link>
            <a href='#features' className='inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-[var(--bg-border)] bg-white/[0.03] px-5 text-sm font-semibold text-[var(--text-secondary)] transition-colors hover:bg-white/[0.07] hover:text-white'>Explore what it does <ArrowDown className='h-4 w-4' aria-hidden='true' /></a>
          </div>
          <p className='mt-4 text-xs text-[var(--text-muted)]'>Your transactions stay under your control. Review details before saving.</p>
        </div>

        <div className='relative mx-auto w-full max-w-lg'>
          <div className='absolute -inset-5 rounded-[2rem] bg-gradient-to-br from-purple-500/20 via-transparent to-blue-500/10 blur-xl' aria-hidden='true' />
          <div className='relative rounded-[1.75rem] border border-white/10 bg-[#111114]/95 p-5 shadow-2xl shadow-black/40 sm:p-7'>
            <div className='flex items-center justify-between border-b border-white/10 pb-5'>
              <div>
                <p className='text-xs font-medium text-[var(--text-muted)]'>YOUR MONEY, AT A GLANCE</p>
                <p className='mt-1 text-lg font-semibold'>A clearer everyday view</p>
              </div>
              <span className='flex h-10 w-10 items-center justify-center rounded-xl bg-purple-400/10 text-purple-300'><Wallet className='h-5 w-5' aria-hidden='true' /></span>
            </div>
            <div className='grid grid-cols-2 gap-3 py-5'>
              <div className='rounded-2xl border border-white/10 bg-white/[0.03] p-4'><p className='text-xs text-[var(--text-muted)]'>Accounts</p><p className='mt-2 text-sm font-semibold'>Together in one view</p></div>
              <div className='rounded-2xl border border-white/10 bg-white/[0.03] p-4'><p className='text-xs text-[var(--text-muted)]'>Transactions</p><p className='mt-2 text-sm font-semibold'>Easy to review</p></div>
            </div>
            <div className='rounded-2xl border border-purple-400/20 bg-purple-400/[0.07] p-4'>
              <div className='flex items-start gap-3'>
                <span className='flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-purple-400/15 text-purple-200'><Bot className='h-5 w-5' aria-hidden='true' /></span>
                <div><p className='text-xs font-semibold uppercase tracking-wide text-purple-200'>Your assistant</p><p className='mt-1 text-sm leading-6 text-[var(--text-secondary)]'>“Spent 450 on lunch” or “How much do I owe?” Start with a question or a quick note.</p></div>
              </div>
            </div>
            <div className='mt-4 flex flex-wrap gap-2'>
              {[['Chat', Bot], ['Voice', Mic], ['Receipt', Camera]].map(([label, Icon]) => {
                const ItemIcon = Icon as typeof Bot;
                return <span key={label as string} className='inline-flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1.5 text-xs text-[var(--text-muted)]'><ItemIcon className='h-3.5 w-3.5' aria-hidden='true' />{label as string}</span>;
              })}
            </div>
            <p className='mt-4 text-[11px] text-[var(--text-muted)]'>Illustrative preview · no sample account data</p>
          </div>
        </div>
      </section>

      <section id='features' className='border-y border-white/[0.06] bg-white/[0.015]'>
        <div className='mx-auto max-w-7xl px-5 py-16 sm:px-8 lg:px-10 lg:py-20'>
          <p className='text-xs font-semibold uppercase tracking-[0.18em] text-[var(--brand-primary)]'>One place for the moving parts</p>
          <div className='mt-3 flex flex-col justify-between gap-4 md:flex-row md:items-end'>
            <h2 className='max-w-2xl text-3xl font-bold tracking-tight sm:text-4xl'>A personal finance toolkit that speaks your language.</h2>
            <p className='max-w-md text-sm leading-6 text-[var(--text-secondary)]'>From recording a purchase to figuring out a shared bill, keep the everyday details connected.</p>
          </div>
          <div className='mt-9 grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
            {features.map(({ icon: Icon, title, description }, index) => (
              <article key={title} className='rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-5 transition-transform hover:-translate-y-1'>
                <span className='flex h-11 w-11 items-center justify-center rounded-2xl bg-[var(--brand-primary)]/10 text-purple-300'><Icon className='h-5 w-5' aria-hidden='true' /></span>
                <p className='mt-5 text-xs font-semibold text-[var(--brand-primary)]'>0{index + 1}</p>
                <h3 className='mt-1 text-base font-semibold'>{title}</h3>
                <p className='mt-2 text-sm leading-6 text-[var(--text-secondary)]'>{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id='how-it-works' className='mx-auto max-w-7xl px-5 py-16 sm:px-8 lg:px-10 lg:py-20'>
        <div className='grid gap-10 lg:grid-cols-[0.8fr_1.2fr]'>
          <div>
            <p className='text-xs font-semibold uppercase tracking-[0.18em] text-[var(--brand-primary)]'>A simple rhythm</p>
            <h2 className='mt-3 text-3xl font-bold tracking-tight sm:text-4xl'>Start small. Get a fuller picture over time.</h2>
            <p className='mt-4 text-sm leading-6 text-[var(--text-secondary)]'>You decide what to record and what to remember. AffordAbled helps connect the details as you use it.</p>
          </div>
          <ol className='space-y-3'>
            {steps.map(([title, description], index) => (
              <li key={title} className='flex gap-4 rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-5'>
                <span className='flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--brand-primary)]/15 text-sm font-bold text-purple-200'>{index + 1}</span>
                <div><h3 className='font-semibold'>{title}</h3><p className='mt-1 text-sm leading-6 text-[var(--text-secondary)]'>{description}</p></div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id='help' className='border-t border-white/[0.06] bg-white/[0.015]'>
        <div className='mx-auto grid max-w-7xl gap-8 px-5 py-16 sm:px-8 md:grid-cols-[0.7fr_1.3fr] lg:px-10 lg:py-20'>
          <div>
            <span className='flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-400/10 text-blue-300'><CircleHelp className='h-5 w-5' aria-hidden='true' /></span>
            <p className='mt-4 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--brand-primary)]'>A few useful details</p>
            <h2 className='mt-2 text-3xl font-bold tracking-tight'>Good to know</h2>
          </div>
          <div className='divide-y divide-white/10'>
            <article className='py-4 first:pt-0'><h3 className='font-semibold'>Do I need to use the assistant?</h3><p className='mt-2 text-sm leading-6 text-[var(--text-secondary)]'>No. You can add transactions manually and manage accounts, categories, and splits through the app.</p></article>
            <article className='py-4'><h3 className='font-semibold'>Does a receipt get saved as a transaction immediately?</h3><p className='mt-2 text-sm leading-6 text-[var(--text-secondary)]'>Receipt text can be sent to the assistant for processing. When it needs review, you can check or edit the details before saving.</p></article>
            <article className='py-4'><h3 className='font-semibold'>Can I review assistant preferences?</h3><p className='mt-2 text-sm leading-6 text-[var(--text-secondary)]'>Yes. Suggested preferences can be accepted or dismissed, and saved memories can be reviewed from your profile.</p></article>
            <article className='py-4'><h3 className='font-semibold'>Need a hand getting started?</h3><p className='mt-2 text-sm leading-6 text-[var(--text-secondary)]'>Create an account, add an account and a few categories, then try a short chat request such as “Spent 250 on lunch.”</p></article>
          </div>
        </div>
      </section>

      <section className='mx-auto max-w-7xl px-5 py-14 sm:px-8 lg:px-10'>
        <div className='flex flex-col items-start justify-between gap-5 rounded-[1.75rem] border border-purple-400/20 bg-gradient-to-r from-purple-500/10 via-purple-500/[0.04] to-blue-500/[0.06] p-6 sm:p-9 md:flex-row md:items-center'>
          <div><p className='text-sm font-semibold text-purple-200'>Ready when you are</p><h2 className='mt-1 text-2xl font-bold'>Make the next money moment a little easier.</h2></div>
          <Link to='/register' className='inline-flex min-h-11 shrink-0 items-center gap-2 rounded-xl bg-[var(--brand-primary)] px-5 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-hover)]'>Get started <ArrowRight className='h-4 w-4' aria-hidden='true' /></Link>
        </div>
      </section>

      <footer className='mx-auto flex max-w-7xl flex-col gap-2 border-t border-white/[0.06] px-5 py-6 text-xs text-[var(--text-muted)] sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-10'>
        <div className='inline-flex w-fit flex-wrap items-center gap-2 rounded-2xl border border-purple-400/15 bg-purple-400/[0.04] px-3 py-2'>
          <span className='text-[var(--text-secondary)]'><strong className='font-bold tracking-[0.08em] text-[var(--text-primary)]'>{APP_NAME}</strong><span className='mx-1.5 text-purple-300/70'>·</span>Personal AI Wallet</span>
          <a href='https://github.com/HazSyl1' target='_blank' rel='noreferrer' className='inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[var(--text-secondary)] transition-colors hover:border-purple-300/30 hover:bg-purple-400/10 hover:text-purple-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'>
            Made by Sarthak C <span aria-hidden='true'>↗</span>
          </a>
          <a href='mailto:sarchaure911@gmail.com' className='inline-flex items-center gap-1.5 rounded-full border border-purple-400/25 bg-purple-400/[0.07] px-3 py-1.5 font-medium text-purple-200 transition-colors hover:border-purple-300/50 hover:bg-purple-400/[0.14] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'>
            <Mail className='h-3.5 w-3.5' aria-hidden='true' />
            Contact developer
          </a>
        </div>
        <span className='inline-flex items-center gap-1.5'><Check className='h-3.5 w-3.5 text-emerald-300' aria-hidden='true' /> You stay in control of what gets recorded.</span>
      </footer>
    </main>
  );
}

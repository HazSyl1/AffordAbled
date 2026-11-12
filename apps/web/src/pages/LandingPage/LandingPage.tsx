import {
  ArrowRight, Bot, Camera, Check, CircleHelp, FileDown, Mail,
  Plus, ReceiptText, ShieldCheck, Split, Wallet, Users, BadgePercent, Scale, ListChecks, Repeat2, QrCode, Gauge,
} from 'lucide-react';
import { Link } from 'react-router-dom';

import { APP_NAME } from '../../constants';
import { useAppSelector } from '../../app/hooks';
import { AffordableWordmark } from '../../components/brand/AffordableLogo';
import { ThemeControl } from '../../components/molecules/ThemeControl';
import './LandingPage.css';
import { AccountStory, CaptureStory, RecurringStory, GroupStory, FinanceChatStory, FeatureBento, Reveal } from './LandingStories';
import { LandingHero } from './LandingHero';
import { FeatureCarousel } from './FeatureCarousel';

const features = [
  {
    icon: Wallet,
    title: 'Keep your accounts together',
    description: 'Track balances across bank, card, cash, and wallet accounts. Starter categories are ready when you sign up.',
    how: 'Add your first account after sign-up. Add more from Accounts.',
    location: 'Accounts',
  },
  {
    icon: ReceiptText,
    title: 'Record everyday money',
    description: 'Add expenses, income, refunds, and transfers. Find, edit, or review past entries in one place.',
    how: 'Open Transactions and tap the + button to enter a transaction yourself.',
    location: 'Transactions',
  },
  {
    icon: Repeat2,
    title: 'Stay ahead of recurring money',
    description: 'Schedule regular expenses and income such as rent, subscriptions, and salary. Transactions are posted at the right time.',
    how: 'Enable Repeat while adding a transaction, manage schedules in the Recurring tab, or ask Finance Chat.',
    location: 'Transactions',
  },
  {
    icon: Bot,
    title: 'Ask your wallet',
    description: 'Describe a purchase in your own words or ask about your recorded spending and transactions.',
    how: 'Open Finance Chat and try “Spent ₹450 on lunch” or “What did I spend on food this month?”',
    location: 'Finance Chat',
  },
  {
    icon: Camera,
    title: 'Use a receipt or your voice',
    description: 'Send a receipt image or dictate a request, then check the extracted details and any follow-up questions.',
    how: 'Use the image or microphone button beside the Finance Chat message box.',
    location: 'Finance Chat',
  },
  {
    icon: Split,
    title: 'Split a bill fairly',
    description: 'Share an expense equally, set custom shares, or allocate priced items to the people who had them.',
    how: 'Open Splits, choose Split an expense, select the transaction, and review everyone’s share.',
    location: 'Splits',
  },
  {
    icon: Plus,
    title: 'Track IOUs and repayments',
    description: 'Record money someone owes you even without an expense, and mark received payments in your account.',
    how: 'Use Record money owed in Splits. Choose Received in before tapping Mark repaid.',
    location: 'Splits',
  },
  {
    icon: Users,
    title: 'Plan a group settlement',
    description: 'Combine several bills, payers, and shared items into one plan. See who owes whom before anything is saved.',
    how: 'Open Splits, choose Plan group settlement, then review the preview. Finance Chat can prepare a draft too.',
    location: 'Splits',
  },
  {
    icon: BadgePercent,
    title: 'Coupons, fees, and tips',
    description: 'Apply a coupon before or after fees, add card fees or tips by percentage, and let different people cover them.',
    how: 'Add them to a bill in the planner. “Paid by” is who paid the merchant; “Shared by” is who bears the cost.',
    location: 'Splits',
  },
  {
    icon: Scale,
    title: 'Settle with exact math',
    description: 'Amounts are checked to the paisa, so payments must match each bill’s total. Settled transfers are tracked as you go.',
    how: 'Mark transfers settled in Splits. Only payments involving you create wallet transactions; edit a plan to recalculate the rest.',
    location: 'Splits',
  },
  {
    icon: ListChecks,
    title: 'Several requests, one message',
    description: 'Ask for more than one thing at once, such as creating categories. The assistant finishes each task, then shows a summary.',
    how: 'Try “Create categories Food and Misc” in Finance Chat. Money is only saved after you confirm it.',
    location: 'Finance Chat',
  },
  {
    icon: FileDown,
    title: 'Bring your history along',
    description: 'Preview CSV or Excel imports before saving, then export transactions as CSV, Excel, or PDF.',
    how: 'Use Import or Export at the top of Transactions; a CSV template is available there.',
    location: 'Transactions',
  },
  {
    icon: QrCode,
    title: 'Send UPI payment reminders',
    description: 'Email everyone who still owes you a branded request with the amount, a Pay with UPI button, and a QR code.',
    how: 'Save your UPI ID in Profile, then open a split and choose Send reminders. Missing emails are collected first.',
    location: 'Splits',
  },
  {
    icon: Gauge,
    title: 'Plans and daily usage',
    description: 'See your plan and how much of today’s AI chat and AI-created transaction allowance is left.',
    how: 'Open Profile to view usage. Allowances reset every day at midnight UTC.',
    location: 'Profile',
  },
  {
    icon: ShieldCheck,
    title: 'Choose what gets remembered',
    description: 'Review suggested preferences before they guide future assistance. Remove saved preferences when they change.',
    how: 'Review suggestions when they appear, and manage confirmed preferences in Profile.',
    location: 'Profile',
  },
];

const steps = [
  ['Create your wallet', 'Register and add your first bank, card, cash, or wallet account. You can start with a zero balance.'],
  ['Record something', 'Tap + in Transactions, or tell Finance Chat what you spent. You can also use a receipt image or voice.'],
  ['Check the result', 'Review the details and category, answer any follow-up question, and find the entry in Transactions.'],
  ['See the bigger picture', 'Use Dashboard for a monthly summary, or open Splits to track shared expenses and repayments.'],
];

export function LandingPage() {
  const isAuthenticated = Boolean(useAppSelector((state) => state.auth.accessToken));
  const destination = isAuthenticated ? '/dashboard' : '/register';
  return (
    <main className='landing-restored min-h-screen text-[var(--text-primary)]'>
      <header className='mx-auto flex w-full max-w-7xl items-center justify-between px-5 py-5 sm:px-8 lg:px-10'>
        <Link to='/' className='inline-flex items-center gap-3 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]'>
          <AffordableWordmark size={44} />
        </Link>
        <nav aria-label='Main navigation' className='flex items-center gap-2 sm:gap-3'>
          <a href='#whats-new' className='hidden rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-white md:inline-flex'>What’s new</a>
          <a href='#features' className='hidden rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-white md:inline-flex'>Features</a>
          <a href='#how-it-works' className='hidden rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:text-white md:inline-flex'>How to use it</a>
          <a href='#help' className='hidden rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] md:inline-flex'>FAQs</a>
          <ThemeControl compact />
          <details className='premium-mobile-menu md:hidden'>
            <summary>Menu</summary>
            <div><a href='#features'>Features</a><a href='#how-it-works'>How to use it</a><a href='#help'>FAQs</a></div>
          </details>
          {!isAuthenticated && <Link to='/login' className='rounded-xl px-3 py-2 text-sm font-semibold text-[var(--text-secondary)] transition-colors hover:bg-white/5 hover:text-white'>Log in</Link>}
          <Link to={destination} className='inline-flex items-center gap-2 rounded-xl bg-[var(--brand-primary)] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-hover)]'>{isAuthenticated ? 'Open app' : 'Get started'} <ArrowRight className='h-4 w-4' aria-hidden='true' /></Link>
        </nav>
      </header>

      <LandingHero signedIn={isAuthenticated} />

      <FeatureCarousel />

      <AccountStory />
      <CaptureStory />
      <RecurringStory />
      <GroupStory />
      <FinanceChatStory />
      <FeatureBento />

      <section className='story-container capability-guide'>
        <details><summary>Explore the full feature guide</summary><div className='capability-guide-content'>
          {features.map(({ title, description, how, location }) => <article key={title}><h3>{title}</h3><p>{description}</p><p><strong>{location}:</strong> {how}</p></article>)}
        </div></details>
      </section>

      <section id='how-it-works' className='mx-auto max-w-7xl px-5 py-16 sm:px-8 lg:px-10 lg:py-20'>
        <div className='grid gap-10 lg:grid-cols-[0.8fr_1.2fr]'>
          <div>
            <p className='text-xs font-semibold uppercase tracking-[0.18em] text-[var(--brand-primary)]'>Your first few minutes</p>
            <h2 className='mt-3 text-3xl font-bold tracking-tight sm:text-4xl'>From sign-up to your first useful insight.</h2>
            <p className='mt-4 text-sm leading-6 text-[var(--text-secondary)]'>Starter categories are ready for you. Add an account, record a purchase, and check the result before exploring your dashboard or splitting a bill.</p>
            <Link to={destination} className='mt-6 inline-flex items-center gap-2 text-sm font-semibold text-purple-200 hover:text-white'>{isAuthenticated ? 'Open app' : 'Create your wallet'} <ArrowRight className='h-4 w-4' aria-hidden='true' /></Link>
          </div>
          <ol className='landing-journey'>
            {steps.map(([title, description], index) => (
              <li key={title} className='flex gap-4 p-5'>
                <span className='flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--brand-primary)]/15 text-sm font-bold text-purple-200'>{index + 1}</span>
                <div><h3 className='font-semibold'>{title}</h3><p className='mt-1 text-sm leading-6 text-[var(--text-secondary)]'>{description}</p></div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className='story-container product-principles'><Reveal><h2>The assistant helps.<br />You keep the final say.</h2><div><p><strong>Review the consequence.</strong> Check the amount, account, and people before confirming.</p><p><strong>Choose what’s remembered.</strong> Accept or dismiss suggested preferences.</p><p><strong>Keep the details visible.</strong> See how transfers and settlements affect your records.</p></div></Reveal></section>

      <section id='help' className='border-t border-white/[0.06] bg-white/[0.015]'>
        <div className='mx-auto grid max-w-7xl gap-8 px-5 py-16 sm:px-8 md:grid-cols-[0.7fr_1.3fr] lg:px-10 lg:py-20'>
          <div>
            <span className='flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-400/10 text-blue-300'><CircleHelp className='h-5 w-5' aria-hidden='true' /></span>
            <p className='mt-4 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--brand-primary)]'>A few useful details</p>
            <h2 className='mt-2 text-3xl font-bold tracking-tight'>Good to know</h2>
          </div>
          <div className='divide-y divide-white/10'>
            <details className='landing-faq'><summary>Do I need to use the assistant?<span aria-hidden='true'>+</span></summary><div><p>No. You can add transactions manually and manage accounts, categories, and splits through the app.</p></div></details>
            <details className='landing-faq'><summary>What if a receipt needs more detail?<span aria-hidden='true'>+</span></summary><div><p>Upload it in Finance Chat. The assistant can ask about anything unclear; check the transaction and its category when it appears.</p></div></details>
            <details className='landing-faq'><summary>Can I record money owed without logging a purchase?<span aria-hidden='true'>+</span></summary><div><p>Yes. Open Splits and choose Record money owed. When someone pays you back, choose the receiving account and mark it repaid.</p></div></details>
            <details className='landing-faq'><summary>How do I split a bill with coupons, fees, or several payers?<span aria-hidden='true'>+</span></summary><div><p>Open Splits and choose Plan group settlement. Add each bill, who shared each item, who paid, and any coupon, fee, or tip. Previewing never touches your wallet; confirming records only your own payments.</p></div></details>
            <details className='landing-faq'><summary>Can I review assistant preferences?<span aria-hidden='true'>+</span></summary><div><p>Yes. Suggested preferences can be accepted or dismissed, and saved memories can be reviewed from your profile.</p></div></details>
            <details className='landing-faq'><summary>Where do I start?<span aria-hidden='true'>+</span></summary><div><p>Register and add your first money account. Starter categories are already there, so you can record a purchase in Transactions or Finance Chat.</p></div></details>
          </div>
        </div>
      </section>

      <section className='mx-auto max-w-7xl px-5 py-14 sm:px-8 lg:px-10'>
        <div className='flex flex-col items-start justify-between gap-5 rounded-[1.75rem] border border-purple-400/20 bg-gradient-to-r from-purple-500/10 via-purple-500/[0.04] to-blue-500/[0.06] p-6 sm:p-9 md:flex-row md:items-center'>
          <div><p className='text-sm font-semibold text-purple-200'>Ready when you are</p><h2 className='mt-1 text-2xl font-bold'>Make the next money moment a little easier.</h2></div>
          <Link to={destination} className='inline-flex min-h-11 shrink-0 items-center gap-2 rounded-xl bg-[var(--brand-primary)] px-5 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-hover)]'>{isAuthenticated ? 'Open app' : 'Get started'} <ArrowRight className='h-4 w-4' aria-hidden='true' /></Link>
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
      <p className='mx-auto max-w-7xl px-5 pb-6 text-center text-[11px] text-[var(--text-muted)] sm:px-8 lg:px-10'>
        {APP_NAME} uses AI and may make mistakes. Please double-check its responses.
      </p>
    </main>
  );
}

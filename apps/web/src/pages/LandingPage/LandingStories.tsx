import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Camera, Check, Keyboard, Mic, Repeat2, Users } from 'lucide-react';

export function Reveal({ children, className = '' }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !('IntersectionObserver' in window) || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    const node = ref.current;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        node.animate([{ opacity: .4, transform: 'translateY(20px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 650, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' });
        observer.disconnect();
      }
    }, { threshold: .15 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return <div ref={ref} className={className}>{children}</div>;
}

const walletStages = [
  ['Your accounts. One clear view.', 'Keep bank, cash, card, and wallet balances together without switching between screens.'],
  ['Every transaction has a place.', 'Review expenses, income, refunds, and transfers alongside their accounts and categories.'],
  ['See where the month went.', 'Follow your spending by category, then return to the entries behind the totals.'],
  ['A little perspective helps.', 'Your dashboard brings monthly income, spending, and shared costs into focus.'],
];

function WalletStage({ stage }: { stage: number }) {
  return <div className='story-panel wallet-stage'>
    <div className='story-panel-top'><strong>{['Wallet', 'Activity', 'Categories', 'Monthly overview'][stage]}</strong><span>Illustrative example</span></div>
    <div key={stage} className='story-state'>
      {stage === 0 && <><p className='story-muted'>Across your accounts</p><p className='story-money money'>₹48,250.00</p>{[['Bank account', '₹42,000'], ['Cash', '₹4,250'], ['Wallet', '₹2,000']].map(([name, amount]) => <div className='story-row' key={name}><span>{name}</span><strong className='money'>{amount}</strong></div>)}</>}
      {stage === 1 && <>{[['Lunch with friends', 'Food · Today', '−₹900'], ['Metro recharge', 'Travel · Yesterday', '−₹500'], ['Project payment', 'Income · Monday', '+₹18,000']].map(([name, note, amount]) => <div className='story-row' key={name}><div><strong>{name}</strong><small>{note}</small></div><strong className='money'>{amount}</strong></div>)}<p className='story-footnote'>Find the account, category, and date behind each entry.</p></>}
      {stage === 2 && <><p className='story-muted'>Spending by category</p>{[['Food & dining', '₹3,240', 80], ['Shopping', '₹2,810', 69], ['Travel', '₹1,410', 35]].map(([name, amount, width]) => <div className='story-category' key={name}><div><span>{name}</span><strong className='money'>{amount}</strong></div><div className='story-track'><span style={{ width: `${width}%` }} /></div></div>)}</>}
      {stage === 3 && <><p className='story-muted'>This month</p><div className='story-summary'><div><small>Income</small><strong className='money'>₹32,000</strong></div><div><small>Spent</small><strong className='money'>₹7,460</strong></div></div><div className='story-insight'>Follow the totals.<br /><strong>Then explore the details.</strong></div><p className='story-footnote'>A summary of recorded activity, not a prediction or financial advice.</p></>}
    </div>
    <div className='story-stage-indicators' aria-hidden='true'>{walletStages.map((_, index) => <span key={index} data-active={index === stage} />)}</div>
  </div>;
}

export function AccountStory() {
  const [stage, setStage] = useState(0);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!('IntersectionObserver' in window)) return;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => { if (entry.isIntersecting) setStage(Number((entry.target as HTMLElement).dataset.stage)); });
    }, { rootMargin: '-25% 0px -40% 0px', threshold: 0 });
    ref.current?.querySelectorAll('[data-stage]').forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);
  return <section id='features' className='account-story story-container' ref={ref} aria-labelledby='accounts-heading'>
    <Reveal><h2 id='accounts-heading'>Everything in one place.</h2><p className='story-intro'>Less switching. More understanding.</p></Reveal>
    <div className='account-story-layout'><div>{walletStages.map(([title, description], index) => <div className='account-story-step' data-stage={index} key={title}><h3>{title}</h3><p>{description}</p><div className='wallet-mobile-preview'><WalletStage stage={index} /></div></div>)}</div><div className='wallet-desktop-preview'><WalletStage stage={stage} /></div></div>
  </section>;
}

const captureModes = [
  { name: 'Receipt', icon: Camera, input: 'Lunch receipt · ₹450', note: 'Merchant and amount extracted for review.' },
  { name: 'Voice', icon: Mic, input: '“Spent four hundred and fifty on lunch.”', note: 'Your words become a transaction draft.' },
  { name: 'Manual', icon: Keyboard, input: 'Expense · ₹450 · Lunch', note: 'Enter the amount, account, and category yourself.' },
];

export function CaptureStory() {
  const [mode, setMode] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  return <section className='story-section story-container'><Reveal className='story-two-column'>
    <div className='story-copy'><h2>Capture spending.<br /><span>Keep moving.</span></h2><p>A receipt, a few words, or a quick entry. Start your way, check the details, and keep your records together.</p><p className='story-footnote'>You review the consequence before a financial record changes.</p></div>
    <div className='story-panel'><div className='story-panel-top'><strong>Record a transaction</strong><span>Interactive demo</span></div><div className='story-choice-group' role='group' aria-label='Capture method'>{captureModes.map(({ name, icon: Icon }, index) => <button type='button' aria-pressed={mode === index} onClick={() => { setMode(index); setConfirmed(false); }} key={name}><Icon size={16} aria-hidden='true' />{name}</button>)}</div><div key={mode} className='story-state'><div className='capture-input'>{captureModes[mode].input}</div><p className='story-footnote'>{captureModes[mode].note}</p><div className='story-row'><span>Amount</span><strong className='money'>₹450.00</strong></div><div className='story-row'><span>Category</span><strong>Food & dining</strong></div><div className='story-row'><span>Account</span><strong>Bank account</strong></div></div><button className='premium-primary story-confirm' type='button' onClick={() => setConfirmed(true)}>{confirmed ? 'Demo confirmed' : 'Try the review step'}<Check size={16} aria-hidden='true' /></button><p className='story-footnote' aria-live='polite'>{confirmed ? 'Preview only. No transaction was saved.' : 'Illustrative data. This demo does not access your wallet.'}</p></div>
  </Reveal></section>;
}

export function RecurringStory() {
  return <section className='story-section story-section-alt'><Reveal className='story-container story-two-column story-reverse'><div className='story-copy'><h2>Stay ahead of<br /><span>the recurring things.</span></h2><p>Rent, subscriptions, salary. Set a schedule for the money that repeats, and manage it alongside your transactions.</p><p className='story-footnote'>Scheduled transactions are recorded at the right time. Split payment reminders are sent only after your confirmation.</p></div><div className='story-panel'><div className='story-panel-top'><strong>Recurring transactions</strong><span>Illustrative example</span></div>{[['Rent', 'Monthly · Next: 1 July', '₹15,000'], ['Music subscription', 'Monthly · Next: 5 July', '₹119'], ['Salary', 'Monthly · Next: 30 July', '₹32,000']].map(([name, date, amount]) => <div className='story-row' key={name}><span className='story-small-icon'><Repeat2 size={18} aria-hidden='true' /></span><div><strong>{name}</strong><small>{date}</small></div><strong className='money'>{amount}</strong></div>)}<div className='story-insight'>Set the rhythm once.<br /><strong>Keep the schedule in view.</strong></div></div></Reveal></section>;
}

export function GroupStory() {
  const [split, setSplit] = useState(false);
  return <section className='story-section story-container'><Reveal className='story-two-column'><div className='story-copy'><h2>Money with people.<br /><span>Without the guesswork.</span></h2><p>Split dinner, track an IOU, or settle a whole trip. Include coupons, fees, tips, and several payers in one reviewable plan.</p><p className='story-footnote'>Payments are checked to the paisa. Only your own confirmed payments affect your wallet.</p></div><div className='story-panel'><div className='story-panel-top'><strong>Dinner together</strong><span>Interactive demo</span></div><p className='story-money money'>₹1,200.00</p><p className='story-muted'>Paid by you · Shared equally by four</p><div className='split-people'>{['You', 'Isha', 'Piyush', 'Dev'].map((name) => <div key={name}><span>{name[0]}</span><strong>{name}</strong></div>)}</div><button type='button' className='premium-primary story-confirm' onClick={() => setSplit(!split)}>{split ? 'Reset preview' : 'Preview the split'}<Users size={16} aria-hidden='true' /></button><div className='split-result' aria-live='polite'>{split ? <div className='story-state'>{['Isha', 'Piyush', 'Dev'].map((name) => <div className='story-row' key={name}><span>{name} owes you</span><strong className='money'>₹300</strong></div>)}</div> : <p className='story-muted'>Each person’s share and outstanding amount will appear here.</p>}</div><p className='story-footnote'>Illustrative preview. No split or payment request is created.</p></div></Reveal></section>;
}

const conversations = [
  { label: 'Spending', question: 'How much did I spend on food this month?', answer: '₹7,460 in recorded food spending.', rows: [['Dining', '₹3,240'], ['Delivery', '₹2,810'], ['Groceries', '₹1,410']], note: 'Based on the illustrative transactions in this preview.' },
  { label: 'Split a bill', question: 'Split my ₹1,200 dinner equally with Isha, Piyush and Dev.', answer: 'That’s ₹300 each, including your share.', rows: [['Isha', '₹300'], ['Piyush', '₹300'], ['Dev', '₹300']], note: 'Review the people, payer, and amounts before saving.' },
  { label: 'Several requests', question: 'Create categories Food and Misc as expenses.', answer: 'Two requests, handled in turn.', rows: [['Food', 'Expense category'], ['Misc', 'Expense category']], note: 'The assistant returns a summary of the completed tasks.' },
];

export function FinanceChatStory() {
  const [index, setIndex] = useState(0);
  const chat = conversations[index];
  return <section id='examples' className='story-section story-section-alt'><Reveal className='story-container story-chat-layout'><div className='story-copy'><h2>Ask AffordAbled.</h2><p>Natural questions. Answers grounded in your recorded activity. Describe a purchase, explore spending, or prepare a split without navigating every screen.</p><div className='story-choice-group' role='group' aria-label='Finance Chat examples'>{conversations.map((item, i) => <button type='button' key={item.label} aria-pressed={i === index} onClick={() => setIndex(i)}>{item.label}</button>)}</div></div><div className='story-panel chat-preview'><div className='story-panel-top'><strong>Finance Chat</strong><span>Illustrative conversation</span></div><div className='story-state' key={index} aria-live='polite'><p className='chat-question'>{chat.question}</p><div className='chat-answer'><strong>{chat.answer}</strong>{chat.rows.map(([name, value]) => <div className='story-row' key={name}><span>{name}</span><strong>{value}</strong></div>)}<p className='story-footnote'>{chat.note}</p></div></div><div className='chat-composer' aria-hidden='true'>Ask anything about your money…<span>↑</span></div></div></Reveal></section>;
}

export function FeatureBento() {
  return <section className='story-section story-container'><Reveal><h2>The details are covered, too.</h2><div className='feature-bento'>
    <article className='bento-wide'><h3>Your history travels with you.</h3><p>Preview CSV or Excel imports. Export transactions as CSV, Excel, or PDF.</p><div className='bento-file-row'><span>transactions.csv</span><span>Ready to preview</span></div><div className='bento-format-row'><span>CSV</span><span>Excel</span><span>PDF</span></div></article>
    <article><h3>An IOU without a purchase.</h3><p>Record money owed and choose the receiving account when it’s repaid.</p><div className='bento-value'>₹800 <small>owed to you · Demo</small></div></article>
    <article><h3>The extras, accounted for.</h3><p>Include coupons, card fees, and tips in group settlements.</p><div className='bento-format-row'><span>Coupon</span><span>Fee</span><span>Tip</span></div></article>
    <article className='bento-wide'><h3>Remembered with your permission.</h3><p>Accept or dismiss suggested preferences. Review or remove saved preferences in Profile.</p><div className='bento-file-row'><span>Suggested preference</span><span>Review first</span></div></article>
  </div></Reveal></section>;
}

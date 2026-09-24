import type { LucideIcon } from 'lucide-react';
import {
  ArrowLeftRight,
  GitBranch,
  House,
  Image as ImageIcon,
  Landmark,
  MessageCircle,
  Mic,
  Plus,
  User,
} from 'lucide-react';

export const APP_NAME = 'AFFORDABLED';
export const APP_TAGLINE = 'Personal AI Wallet';

export const LAYOUT_UI_TEXT = {
  signedInLabel: 'Signed in',
  accountLabel: 'Personal Wallet',
  openChatAriaLabel: 'Open chat',
  startVoiceAriaLabel: 'Start voice input',
  collapseSidebarAriaLabel: 'Collapse sidebar',
  expandSidebarAriaLabel: 'Expand sidebar',
} as const;

interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { path: '/', label: 'Home', icon: House },
  { path: '/chat', label: 'Chat', icon: MessageCircle },
  { path: '/transactions', label: 'Trans', icon: Landmark },
  { path: '/splits', label: 'Splits', icon: GitBranch },
  { path: '/profile', label: 'Profile', icon: User },
] as const;

export const ACCOUNTS_NAV_ITEM: NavItem = { path: '/accounts', label: 'Accounts', icon: ArrowLeftRight };

export const AUTH_UI_TEXT = {
  emailLabel: 'Email',
  passwordLabel: 'Password',
  loginTitle: 'Log in',
  loginAction: 'Log in',
  registerTitle: 'Create your account',
  registerAction: 'Create account',
  noAccountPrompt: 'No account?',
  registerLinkLabel: 'Register',
  alreadyHaveAccountPrompt: 'Already have an account?',
  loginLinkLabel: 'Log in',
  invalidCredentialsError: 'Invalid email or password.',
  registrationError: 'Could not create an account with those details.',
} as const;

interface DashboardQuickAction {
  icon: LucideIcon;
  label: string;
  key: 'add' | 'chat' | 'voice' | 'image';
}

export const DASHBOARD_QUICK_ACTIONS: readonly DashboardQuickAction[] = [
  { icon: Plus, label: 'Add', key: 'add' },
  { icon: MessageCircle, label: 'Chat', key: 'chat' },
  { icon: Mic, label: 'Voice', key: 'voice' },
  { icon: ImageIcon, label: 'Image', key: 'image' },
] as const;

export type DashboardQuickActionKey = DashboardQuickAction['key'];

export const DASHBOARD_CHAT_UI_TEXT = {
  assistantTitle: 'AI Assistant',
  inputPlaceholder: 'Type your finance question...',
  sendButton: 'Send',
  financePillLabel: 'Finance Chat',
  draftsPillLabel: 'Drafts',
  financeShortLabel: 'F',
  draftsShortLabel: 'D',
  newFinanceChatTitle: '',
  newChatActionLabel: 'New Chat',
  collapseSideToolAriaLabel: 'Collapse chat tools',
  expandSideToolAriaLabel: 'Expand chat tools',
  noDraftsLabel: 'No active drafts.',
  noFinanceChatsLabel: 'No finance chats yet.',
  collapsedChatPanelHint: 'Chat panel is collapsed. Expand to continue.',
  draftExpiryDisclaimer: 'Drafts expire automatically after 72 hours.',
  openFinanceChat: 'Open Finance Chat',
  saveDraftBeforeCloseTitle: 'Save Draft Before Closing?',
  saveDraftBeforeClosePrompt: 'Save this chat as a draft in Finance Chat before closing?',
  saveDraftYesLabel: 'Yes',
  saveDraftNoLabel: 'No',
  imageComingSoon: 'Soon',
  emptyState: 'Ask me to log a transaction, review spending, or continue a finance query.',
  rotatingGreetings: [
    'Hey there! Ready to make your money move smarter?',
    'Welcome back! Want me to log something quickly?',
    'Lets turn your spending into better decisions today.',
    'Need a quick check on your budget or recent expenses?',
  ],
  voiceHint: 'Use the Voice quick action to transcribe and send audio.',
  transactionDetailHint: 'Transaction-specific chats can be continued from the transaction detail screen.',
  assistantError: 'Could not reach the assistant right now. Please try again.',
  voiceError: 'Voice transcription failed. Please upload a clear WAV or OGG clip.',
} as const;

export const SHEET_TITLES = {
  addTransaction: 'Add Transaction',
  addAccount: 'Add Account',
} as const;

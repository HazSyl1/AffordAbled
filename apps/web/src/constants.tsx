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
export const VOICE_CAPTURE_EVENT_NAME = 'affordabled:start-voice-capture';

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
  { path: '/dashboard', label: 'Home', icon: House },
  { path: '/chat', label: 'Chat', icon: MessageCircle },
  { path: '/transactions', label: 'Trans', icon: Landmark },
  { path: '/splits', label: 'Splits', icon: GitBranch },
  { path: '/profile', label: 'Profile', icon: User },
] as const;

export const ACCOUNTS_NAV_ITEM: NavItem = { path: '/accounts', label: 'Accounts', icon: ArrowLeftRight };

export const AUTH_UI_TEXT = {
  nameLabel: 'Full Name',
  dobLabel: 'Date of Birth',
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
  unauthorizedError: 'You are not authorized to do that. Please check your access and try again.',
  sessionExpiredError: 'Your session expired. Please log in again to continue.',
  serviceUnavailableError: 'Service is currently unavailable. Please try again in some time.',
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
  manualPrefillBadgeLabel: 'Manual Prefill',
  manualPrefillHint: 'Low confidence extraction. Review and edit before adding.',
  closeChatTitle: 'Close this chat?',
  closeChatPrompt: 'Choose what to do with this chat before closing.',
  discardAndCloseLabel: 'Discard & close',
  addToChatsLabel: 'Add to Chats',
  addToDraftsLabel: 'Add to Drafts',
  imageComingSoon: 'Soon',
  emptyState: 'Ask me to log a transaction, review spending, or continue a finance query.',
  rotatingGreetings: [
    'Hey there! Ready to make your money move smarter?',
    'Welcome back! Want me to log something quickly?',
    'Lets turn your spending into better decisions today.',
    'Need a quick check on your budget or recent expenses?',
  ],
  voiceHint: 'Use the Voice quick action to transcribe and send audio.',
  voiceRecordingTitle: 'Voice Input',
  voiceRecordingActiveLabel: 'Recording started',
  voiceRecordingStopButton: 'Stop Recording',
  voiceRecordingCancelButton: 'Cancel',
  voiceRecordingMaxDurationSeconds: 90,
  voiceRecordingProcessingLabel: 'Processing your recording...',
  imageError: 'Image analysis failed. Please upload a clear JPG, PNG, or WEBP image.',
  transactionDetailHint: 'Transaction-specific chats can be continued from the transaction detail screen.',
  assistantError: 'Could not reach the assistant right now. Please try again.',
  voicePermissionError: 'Microphone permission is blocked. Please allow microphone access and try again.',
  voiceUnsupportedError: 'Voice recording is not supported in this browser/context. Use Chrome/Edge on localhost or HTTPS.',
  voiceError: 'Voice transcription failed. Please try again with a clear recording.',
  assistantReplyingLabel: 'Assistant is replying...',
} as const;

export const TRANSACTION_UI_TEXT = {
  chatAboutLabel: 'Chat about this transaction',
  editHintLabel: 'Click to edit or add Splits',
} as const;

export const SHEET_TITLES = {
  addTransaction: 'Add Transaction',
  editTransaction: 'Edit Transaction',
  addAccount: 'Add Account',
} as const;

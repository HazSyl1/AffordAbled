export const APP_NAME = 'AFFORDABLED';
export const APP_TAGLINE = 'Personal AI Wallet';

export const NAV_ITEMS = [
  { path: '/', label: 'Home', icon: '🏠' },
  { path: '/transactions', label: 'Trans', icon: '💳' },
  { path: '/splits', label: 'Splits', icon: '🔀' },
  { path: '/profile', label: 'Profile', icon: '👤' },
] as const;

export const ACCOUNTS_NAV_ITEM = { path: '/accounts', label: 'Accounts', icon: '🏦' } as const;

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

export const DASHBOARD_QUICK_ACTIONS = [
  { icon: '➕', label: 'Add', key: 'add' },
  { icon: '💬', label: 'Chat', key: 'chat' },
  { icon: '🎤', label: 'Voice', key: 'voice' },
  { icon: '🖼️', label: 'Image', key: 'image' },
] as const;

export type DashboardQuickActionKey = (typeof DASHBOARD_QUICK_ACTIONS)[number]['key'];

export const DASHBOARD_CHAT_UI_TEXT = {
  assistantTitle: 'AI Assistant',
  inputPlaceholder: 'Type your finance question...',
  sendButton: 'Send',
  imageComingSoon: 'Soon',
  emptyState: 'Ask me to log a transaction, review spending, or continue a finance query.',
  voiceHint: 'Use the Voice quick action to transcribe and send audio.',
  assistantError: 'Could not reach the assistant right now. Please try again.',
  voiceError: 'Voice transcription failed. Please upload a clear WAV or OGG clip.',
} as const;

export const SHEET_TITLES = {
  addTransaction: 'Add Transaction',
  addAccount: 'Add Account',
} as const;

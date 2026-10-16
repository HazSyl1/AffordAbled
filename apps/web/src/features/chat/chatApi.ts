import type { TransactionType } from '../transactions/transactionsApi';
import { apiClient } from '../../lib/apiClient';

export interface ChatRequest {
  message: string;
  thread_id?: string;
  timezone?: string;
}

export interface ChatTransactionProposal {
  type: TransactionType;
  amount_paise: number;
  occurred_at: string;
  account_id: string;
  account_name: string;
  category_id: string;
  category_name: string;
  confidence_score: number;
  merchant: string | null;
  note: string | null;
}

export interface ChatInsight {
  title: string;
  detail: string;
}

export interface ChatResponse {
  thread_id: string;
  message: string;
  tasks_completed: boolean;
  show_completion_popup: boolean;
  pending_transaction_proposal?: ChatTransactionProposal | null;
  pending_transaction_proposals?: ChatTransactionProposal[] | null;
  transaction_logged?: boolean;
  created_transaction_id?: string | null;
  manual_transaction_input_required?: boolean;
  insights?: ChatInsight[] | null;
}

export interface ChatThreadMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface ChatThreadDetail {
  thread: {
    thread_id: string;
    title: string | null;
    created_at: string;
    updated_at: string;
    message_count: number;
  };
  messages: ChatThreadMessage[];
}

export interface VoiceTranscriptionRequest {
  audio: File;
  locale?: string;
}

export interface VoiceTranscriptionResponse {
  transcript: string;
  locale: string;
}

export interface ImageAnalysisRequest {
  image: File;
}

export interface ImageAnalysisResponse {
  extracted_text: string;
  prompt: string;
}

const chatApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    sendChatMessage: builder.mutation<ChatResponse, ChatRequest>({
      query: (body) => ({
        url: '/chat',
        method: 'POST',
        body,
      }),
      // A specialist can create/update categories, accounts, or transactions.
      // Invalidate mounted domain lists after every completed chat turn so a
      // user never needs a browser refresh to see a chat-originated mutation.
      invalidatesTags: ['Category', 'Transaction', 'Account'],
    }),
    getChatThread: builder.query<ChatThreadDetail, string>({
      query: (threadId) => `/threads/${encodeURIComponent(threadId)}`,
    }),
    transcribeVoice: builder.mutation<VoiceTranscriptionResponse, VoiceTranscriptionRequest>({
      query: ({ audio, locale = 'en-IN' }) => {
        const formData = new FormData();
        formData.append('audio', audio);
        formData.append('locale', locale);

        return {
          url: '/chat/voice',
          method: 'POST',
          body: formData,
        };
      },
    }),
    analyzeImage: builder.mutation<ImageAnalysisResponse, ImageAnalysisRequest>({
      query: ({ image }) => {
        const formData = new FormData();
        formData.append('image', image);

        return {
          url: '/chat/image',
          method: 'POST',
          body: formData,
        };
      },
    }),
  }),
});

export const {
  useSendChatMessageMutation,
  useLazyGetChatThreadQuery,
  useTranscribeVoiceMutation,
  useAnalyzeImageMutation,
} = chatApi;

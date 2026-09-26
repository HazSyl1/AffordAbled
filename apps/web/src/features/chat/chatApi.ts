import type { TransactionType } from '../transactions/transactionsApi';
import { apiClient } from '../../lib/apiClient';

export interface ChatRequest {
  message: string;
  thread_id?: string;
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

export interface ChatResponse {
  thread_id: string;
  message: string;
  pending_transaction_proposal?: ChatTransactionProposal | null;
  transaction_logged?: boolean;
  manual_transaction_input_required?: boolean;
}

export interface VoiceTranscriptionRequest {
  audio: File;
  locale?: string;
}

export interface VoiceTranscriptionResponse {
  transcript: string;
  locale: string;
}

const chatApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    sendChatMessage: builder.mutation<ChatResponse, ChatRequest>({
      query: (body) => ({
        url: '/chat',
        method: 'POST',
        body,
      }),
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
  }),
});

export const { useSendChatMessageMutation, useTranscribeVoiceMutation } = chatApi;

import { apiClient } from '../../lib/apiClient';

export interface MemorySuggestion {
  id: string;
  scope: string;
  subject_key: string;
  memory_type: string;
  value: Record<string, unknown>;
  status: 'suggested' | 'confirmed' | 'dismissed';
  confidence: number;
  evidence_count: number;
  created_at: string;
  updated_at: string;
}

const memoryApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    listMemories: builder.query<MemorySuggestion[], void>({
      query: () => '/memories',
      providesTags: ['Memory'],
    }),
    listMemorySuggestions: builder.query<MemorySuggestion[], void>({
      query: () => '/memories/suggestions',
      providesTags: ['Memory'],
    }),
    confirmMemorySuggestion: builder.mutation<MemorySuggestion, string>({
      query: (memoryId) => ({ url: `/memories/${memoryId}/confirm`, method: 'POST' }),
      invalidatesTags: ['Memory'],
    }),
    updateMemorySuggestion: builder.mutation<MemorySuggestion, { memoryId: string; value: Record<string, unknown> }>({
      query: ({ memoryId, value }) => ({ url: `/memories/${memoryId}`, method: 'PATCH', body: { value } }),
      invalidatesTags: ['Memory'],
    }),
    dismissMemorySuggestion: builder.mutation<MemorySuggestion, string>({
      query: (memoryId) => ({ url: `/memories/${memoryId}/dismiss`, method: 'POST' }),
      invalidatesTags: ['Memory'],
    }),
    forgetMemory: builder.mutation<void, string>({
      query: (memoryId) => ({ url: `/memories/${memoryId}`, method: 'DELETE' }),
      invalidatesTags: ['Memory'],
    }),
  }),
});

export const {
  useListMemoriesQuery,
  useListMemorySuggestionsQuery,
  useConfirmMemorySuggestionMutation,
  useUpdateMemorySuggestionMutation,
  useDismissMemorySuggestionMutation,
  useForgetMemoryMutation,
} = memoryApi;

import { apiClient } from '../../lib/apiClient';

export type TransactionExportFormat = 'csv' | 'xlsx' | 'pdf';

export interface TransactionExportResponse {
  export_id: string;
  download_url: string;
  expires_at: string;
  filename: string;
  row_count: number;
}

export interface TransactionImportPreview {
  file_hash: string;
  row_count: number;
  valid_count: number;
  already_imported: boolean;
  preview_rows: Array<{
    row_number: number;
    type: string;
    amount: string;
    amount_paise?: number;
    account: string;
    category: string;
    merchant: string;
    error?: string;
  }>;
  errors: Array<{ row_number: number; message: string }>;
}

function importFormData(file: File, timezone: string, previewHash?: string): FormData {
  const body = new FormData();
  body.append('file', file);
  body.append('timezone', timezone);
  if (previewHash) body.append('preview_hash', previewHash);
  return body;
}

const transactionFilesApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    createTransactionExport: builder.mutation<
      TransactionExportResponse,
      { format: TransactionExportFormat; date_from?: string; date_to?: string; timezone: string }
    >({
      query: (body) => ({ url: '/exports/transactions', method: 'POST', body }),
    }),
    getTransactionExportDownloadUrl: builder.query<
      { export_id: string; download_url: string; expires_at: string }, string
    >({
      query: (exportId) => `/exports/${exportId}/download-url`,
    }),
    previewTransactionImport: builder.mutation<TransactionImportPreview, { file: File; timezone: string }>({
      query: ({ file, timezone }) => ({
        url: '/imports/transactions/preview', method: 'POST', body: importFormData(file, timezone),
      }),
    }),
    confirmTransactionImport: builder.mutation<
      { imported_count: number },
      { file: File; timezone: string; previewHash: string }
    >({
      query: ({ file, timezone, previewHash }) => ({
        url: '/imports/transactions/confirm', method: 'POST', body: importFormData(file, timezone, previewHash),
      }),
      invalidatesTags: ['Transaction', 'Account'],
    }),
  }),
});

export const {
  useCreateTransactionExportMutation,
  useLazyGetTransactionExportDownloadUrlQuery,
  usePreviewTransactionImportMutation,
  useConfirmTransactionImportMutation,
} = transactionFilesApi;

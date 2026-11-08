import { useCallback, useState } from 'react';

import {
  type ChatResponse,
  type ChatTurnStatusResponse,
  type ChatTurnSubmitRequest,
  useLazyGetChatTurnStatusQuery,
  useSubmitChatTurnMutation,
} from './chatApi';

const POLL_INTERVAL_MS = 1_500;

function waitForNextCheck(): Promise<void> {
  if (document.visibilityState === 'visible') {
    return new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
  }
  return new Promise((resolve) => {
    const handleVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      document.removeEventListener('visibilitychange', handleVisibility);
      resolve();
    };
    document.addEventListener('visibilitychange', handleVisibility);
  });
}

function completedResult(status: ChatTurnStatusResponse): ChatResponse | null {
  if (status.status === 'failed') {
    throw new Error(status.error_message || 'The assistant could not process this request.');
  }
  if (status.status === 'succeeded') {
    if (!status.result) throw new Error('The completed chat turn did not include a result.');
    return status.result;
  }
  return null;
}

function permanentRequestError(error: unknown): Error | null {
  if (!error || typeof error !== 'object' || !('status' in error)) return null;
  const apiError = error as { status?: unknown; data?: unknown };
  const status = apiError.status;
  if (typeof status !== 'number' || status < 400 || status >= 500 || status === 408) {
    return null;
  }
  if (status === 429) {
    const data = apiError.data as { detail?: { message?: unknown } } | undefined;
    const message = data?.detail?.message;
    return new Error(typeof message === 'string' ? message : 'You have reached today\'s chat limit.');
  }
  return new Error('The chat turn could not be submitted. Please try again with a new message.');
}

export function useDurableChatTurn() {
  const [submitChatTurn] = useSubmitChatTurnMutation();
  const [getChatTurnStatus] = useLazyGetChatTurnStatusQuery();
  const [isProcessingTurn, setIsProcessingTurn] = useState(false);

  const runTurn = useCallback(async (request: ChatTurnSubmitRequest): Promise<ChatResponse> => {
    setIsProcessingTurn(true);
    try {
      // POST is intentionally safe to repeat. If the phone lost the response,
      // the server returns the existing job for this turn ID.
      let submitted: ChatTurnStatusResponse;
      while (true) {
        try {
          submitted = await submitChatTurn(request).unwrap();
          break;
        } catch (error) {
          const permanentError = permanentRequestError(error);
          if (permanentError) throw permanentError;
          await waitForNextCheck();
        }
      }

      const immediateResult = completedResult(submitted);
      if (immediateResult) return immediateResult;

      while (true) {
        await waitForNextCheck();
        try {
          const current = await getChatTurnStatus(request.turn_id, false).unwrap();
          const result = completedResult(current);
          if (result) return result;
        } catch (error) {
          if (error instanceof Error) throw error;
          const permanentError = permanentRequestError(error);
          if (permanentError) throw permanentError;
          // A network error is not a failed turn. Keep the local pending ID and
          // reconcile as soon as the browser becomes visible/online again.
        }
      }
    } finally {
      setIsProcessingTurn(false);
    }
  }, [getChatTurnStatus, submitChatTurn]);

  return { runTurn, isProcessingTurn };
}

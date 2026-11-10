import { useCallback, useState } from 'react';

import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { apiClient } from '../../lib/apiClient';
import { API_BASE_URL } from '../../lib/env';
import {
  type ChatResponse,
  type ChatTurnStatusResponse,
  type ChatTurnSubmitRequest,
  useLazyGetChatTurnStatusQuery,
  useSubmitChatTurnMutation,
} from './chatApi';

// A completed turn should appear promptly after the worker saves it. The API
// only polls while this chat is visible, so this stays bounded per active turn.
const POLL_INTERVAL_MS = 500;

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

async function waitForTurnStream(
  turnId: string,
  accessToken: string,
  signal: AbortSignal,
): Promise<ChatResponse | null> {
  const response = await fetch(`${API_BASE_URL}/api/v1/chat/turns/${encodeURIComponent(turnId)}/events`, {
    headers: { Accept: 'text/event-stream', Authorization: `Bearer ${accessToken}` },
    credentials: 'include',
    signal,
  });
  if (!response.ok || !response.body) return null;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return null;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const event = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
        const data = event.split('\n').find((line) => line.startsWith('data:'))?.slice(5);
        if (!data) continue;
        const status = JSON.parse(data.trim()) as ChatTurnStatusResponse;
        const result = completedResult(status);
        if (result) return result;
      }
    }
  } finally {
    reader.releaseLock();
  }
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
  const dispatch = useAppDispatch();
  const accessToken = useAppSelector((state) => state.auth.accessToken);
  const [submitChatTurn] = useSubmitChatTurnMutation();
  const [getChatTurnStatus] = useLazyGetChatTurnStatusQuery();
  const [isProcessingTurn, setIsProcessingTurn] = useState(false);

  const invalidateFinanceCaches = useCallback(() => {
    dispatch(apiClient.util.invalidateTags(['Category', 'Transaction', 'Account', 'Split', 'Memory']));
  }, [dispatch]);

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
      if (immediateResult) {
        invalidateFinanceCaches();
        return immediateResult;
      }

      // Fetch streaming supports the Authorization header that native EventSource
      // cannot send. A hidden mobile browser aborts the stream; durable polling
      // below resumes when the app becomes visible again.
      if (accessToken && document.visibilityState === 'visible') {
        const controller = new AbortController();
        const stopWhenHidden = () => {
          if (document.visibilityState === 'hidden') controller.abort();
        };
        document.addEventListener('visibilitychange', stopWhenHidden, { once: true });
        try {
          const streamed = await waitForTurnStream(request.turn_id, accessToken, controller.signal);
          if (streamed) {
            invalidateFinanceCaches();
            return streamed;
          }
        } catch {
          // The durable status endpoint below handles expired credentials,
          // reconnects and deployments with a separate API worker process.
        } finally {
          controller.abort();
          document.removeEventListener('visibilitychange', stopWhenHidden);
        }
      }

      while (true) {
        await waitForNextCheck();
        try {
          const current = await getChatTurnStatus(request.turn_id, false).unwrap();
          const result = completedResult(current);
          if (result) {
            invalidateFinanceCaches();
            return result;
          }
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
  }, [accessToken, getChatTurnStatus, invalidateFinanceCaches, submitChatTurn]);

  return { runTurn, isProcessingTurn };
}

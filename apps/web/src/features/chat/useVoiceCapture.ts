import { useCallback, useEffect, useRef, useState } from 'react';

const PREFERRED_MIME_TYPES = [
  'audio/ogg;codecs=opus',
  'audio/ogg',
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
] as const;

export type VoiceCaptureErrorReason = 'permission_denied' | 'unsupported' | 'recording_failed' | 'empty_audio';

interface UseVoiceCaptureOptions {
  maxDurationSeconds?: number;
  onRecorded: (audioFile: File) => Promise<void>;
  onError: (reason: VoiceCaptureErrorReason) => void;
}

interface UseVoiceCaptureResult {
  cancelCapture: () => void;
  elapsedSeconds: number;
  isOpen: boolean;
  isProcessing: boolean;
  startCapture: () => Promise<void>;
  stopCapture: () => void;
}

function extensionFromMimeType(mimeType: string): string {
  const normalized = mimeType.toLowerCase();
  if (normalized.includes('ogg')) {
    return 'ogg';
  }
  if (normalized.includes('mp4') || normalized.includes('m4a')) {
    return 'm4a';
  }
  return 'webm';
}

export function useVoiceCapture({
  maxDurationSeconds = 90,
  onRecorded,
  onError,
}: UseVoiceCaptureOptions): UseVoiceCaptureResult {
  const [isOpen, setIsOpen] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const chunksRef = useRef<Blob[]>([]);
  const discardOnStopRef = useRef(false);
  const intervalRef = useRef<number | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mountedRef = useRef(true);

  const closeAndResetState = useCallback(() => {
    setIsOpen(false);
    setIsProcessing(false);
    setElapsedSeconds(0);
  }, []);

  const clearElapsedTimer = useCallback(() => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const stopMediaStream = useCallback(() => {
    if (!mediaStreamRef.current) {
      return;
    }

    for (const track of mediaStreamRef.current.getTracks()) {
      track.stop();
    }
    mediaStreamRef.current = null;
  }, []);

  const resetRecorderRefs = useCallback(() => {
    mediaRecorderRef.current = null;
    chunksRef.current = [];
    discardOnStopRef.current = false;
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      clearElapsedTimer();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.onstop = null;
        mediaRecorderRef.current.stop();
      }
      stopMediaStream();
      resetRecorderRefs();
    };
  }, [clearElapsedTimer, resetRecorderRefs, stopMediaStream]);

  const stopCapture = useCallback(() => {
    const mediaRecorder = mediaRecorderRef.current;
    if (!mediaRecorder || mediaRecorder.state !== 'recording') {
      return;
    }

    mediaRecorder.stop();
  }, []);

  const cancelCapture = useCallback(() => {
    if (isProcessing) {
      return;
    }

    discardOnStopRef.current = true;
    const mediaRecorder = mediaRecorderRef.current;

    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
      return;
    }

    clearElapsedTimer();
    stopMediaStream();
    resetRecorderRefs();
    if (mountedRef.current) {
      closeAndResetState();
    }
  }, [clearElapsedTimer, closeAndResetState, isProcessing, resetRecorderRefs, stopMediaStream]);

  const startCapture = useCallback(async () => {
    if (!mountedRef.current || isOpen || isProcessing) {
      return;
    }

    if (typeof window === 'undefined' || !window.navigator?.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      console.error('[voice-capture] unsupported runtime: missing getUserMedia or MediaRecorder');
      onError('unsupported');
      return;
    }

    setElapsedSeconds(0);
    setIsProcessing(false);
    setIsOpen(true);

    try {
      const mediaStream = await window.navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = mediaStream;

      const supportedMimeType = PREFERRED_MIME_TYPES.find((mimeType) => MediaRecorder.isTypeSupported(mimeType));
      const mediaRecorder = supportedMimeType
        ? new MediaRecorder(mediaStream, { mimeType: supportedMimeType })
        : new MediaRecorder(mediaStream);

      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onerror = () => {
        clearElapsedTimer();
        stopMediaStream();
        resetRecorderRefs();
        if (mountedRef.current) {
          closeAndResetState();
          onError('recording_failed');
        }
      };

      mediaRecorder.onstop = async () => {
        clearElapsedTimer();
        stopMediaStream();

        if (!mountedRef.current) {
          resetRecorderRefs();
          return;
        }

        if (discardOnStopRef.current) {
          resetRecorderRefs();
          closeAndResetState();
          return;
        }

        setIsProcessing(true);

        try {
          const mimeType = mediaRecorder.mimeType || chunksRef.current[0]?.type || 'audio/webm';
          const audioBlob = new Blob(chunksRef.current, { type: mimeType });
          if (audioBlob.size === 0) {
            throw new Error('empty-audio');
          }

          const extension = extensionFromMimeType(audioBlob.type || mimeType);
          const voiceFile = new File([audioBlob], `voice-note-${Date.now()}.${extension}`, {
            type: audioBlob.type || mimeType,
          });

          await onRecorded(voiceFile);
        } catch (error) {
          if (error instanceof Error && error.message === 'empty-audio') {
            onError('empty_audio');
          } else {
            onError('recording_failed');
          }
        } finally {
          resetRecorderRefs();
          if (mountedRef.current) {
            closeAndResetState();
          }
        }
      };

      mediaRecorder.start();
      intervalRef.current = window.setInterval(() => {
        if (!mountedRef.current) {
          return;
        }

        setElapsedSeconds((value) => {
          const nextValue = value + 1;
          if (nextValue >= maxDurationSeconds) {
            const activeRecorder = mediaRecorderRef.current;
            if (activeRecorder && activeRecorder.state === 'recording') {
              activeRecorder.stop();
            }
            return maxDurationSeconds;
          }
          return nextValue;
        });
      }, 1000);
    } catch (error) {
      clearElapsedTimer();
      stopMediaStream();
      resetRecorderRefs();
      closeAndResetState();

      const isPermissionDenied =
        error instanceof DOMException &&
        ['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(error.name);
      console.error('[voice-capture] start capture failed', error);
      if (isPermissionDenied) {
        onError('permission_denied');
        return;
      }
      onError('recording_failed');
    }
  }, [
    clearElapsedTimer,
    closeAndResetState,
    isOpen,
    isProcessing,
    maxDurationSeconds,
    onError,
    onRecorded,
    resetRecorderRefs,
    stopMediaStream,
  ]);

  return {
    cancelCapture,
    elapsedSeconds,
    isOpen,
    isProcessing,
    startCapture,
    stopCapture,
  };
}

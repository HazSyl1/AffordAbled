const TITLE_MAX_WORDS = 8;
const TITLE_MAX_CHARS = 54;

function limitTitleLength(value: string): string {
  if (value.length <= TITLE_MAX_CHARS) {
    return value;
  }

  return `${value.slice(0, TITLE_MAX_CHARS - 3).trimEnd()}...`;
}

function normalizeGreetingPrefix(value: string): string {
  return value
    .replace(/^(hi|hello|hey|hii|yo)[\s,.:;!-]*/i, '')
    .replace(/^(please|kindly)\s+/i, '')
    .replace(/^(can|could|would)\s+you\s+/i, '')
    .replace(/^i\s+(want|need|would like)\s+to\s+/i, '')
    .replace(/^help\s+me\s+(to\s+)?/i, '')
    .trim();
}

function summarizeGeneralTitle(firstUserMessage: string): string {
  const compactMessage = firstUserMessage.replace(/\s+/g, ' ').trim();
  if (!compactMessage) {
    return '';
  }

  const primarySegment = compactMessage
    .split(/[.!?\n]/)
    .map((segment) => segment.trim())
    .find((segment) => segment.length > 0);

  const sourceText = primarySegment ?? compactMessage;
  const normalizedText = normalizeGreetingPrefix(sourceText);
  const titleSource = normalizedText.length > 0 ? normalizedText : sourceText;
  const words = titleSource.split(' ').filter((word) => word.length > 0);

  if (words.length === 0) {
    return '';
  }

  const truncatedWords = words.slice(0, TITLE_MAX_WORDS);
  let summary = truncatedWords.join(' ');

  if (words.length > TITLE_MAX_WORDS) {
    summary = `${summary}...`;
  }

  const titleCaseSummary = `${summary.charAt(0).toUpperCase()}${summary.slice(1)}`;
  return limitTitleLength(titleCaseSummary);
}

onmessage = (event: MessageEvent<{ firstUserMessage?: string }>) => {
  const firstUserMessage = event.data?.firstUserMessage ?? '';
  const title = summarizeGeneralTitle(firstUserMessage);
  postMessage({ title });
};

export {};

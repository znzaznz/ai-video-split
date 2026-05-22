export type TranscriptSentence = {
  index: number;
  start_ms: number;
  end_ms: number;
  start_hms: string;
  end_hms: string;
  text: string;
};

export type CitationRef = {
  id: string;
  start_hms: string;
  end_hms: string;
  text: string;
};

export type MessageSegment =
  | { kind: "text"; text: string }
  | { kind: "cites"; label: string; refs: CitationRef[] };

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  segments: MessageSegment[];
};

export function isTranscriptSentenceArray(data: unknown): data is TranscriptSentence[] {
  if (!Array.isArray(data) || data.length === 0) return false;
  const s = data[0];
  if (!s || typeof s !== "object") return false;
  const o = s as Record<string, unknown>;
  return (
    typeof o.text === "string" &&
    typeof o.start_hms === "string" &&
    typeof o.end_hms === "string"
  );
}

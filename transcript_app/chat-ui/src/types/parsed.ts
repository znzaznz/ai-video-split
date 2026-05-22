import type { TranscriptSentence } from "@/types/chat";

export type ParsedItem = {
  id: string;
  path: string;
  /** 展示用：runs 下多为任务目录名；平铺的 json 则为文件名 */
  label: string;
  sentences: TranscriptSentence[];
};

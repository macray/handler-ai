// Speaking (D.25), on the phone: a recording made while the microphone is held (nothing listens
// otherwise), Opus at a voice's bitrate (16 kbit/s: a minute fits the gateway's envelope), base64 for
// the host; and an answer read aloud by the device's own voice. The web UI has the same (its lib/voice.ts).
import type { TranscribeParams as SpeechRequest } from "./remote.gen";

export const MAX_SECONDS = 60;

export type Recording = { stop: () => Promise<SpeechRequest | null>; cancel: () => void; started: number };

/** Can this browser record? (a secure context with a microphone) */
export function canRecord(): boolean {
  return typeof MediaRecorder !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
}

/** Starts recording; `stop` gives the recording (null: nothing was said), `cancel` drops it. */
export async function record(onLimit: () => void): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
  const recorder = new MediaRecorder(stream, { mimeType: type || undefined, audioBitsPerSecond: 16_000 });
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const ended = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
  const limit = setTimeout(onLimit, MAX_SECONDS * 1000);
  recorder.start();
  const finish = async (): Promise<Blob> => {
    clearTimeout(limit);
    if (recorder.state !== "inactive") recorder.stop();
    await ended;
    stream.getTracks().forEach((t) => t.stop());
    return new Blob(chunks, { type: recorder.mimeType });
  };
  return {
    started: Date.now(),
    stop: async () => {
      const blob = await finish();
      if (!blob.size) return null;
      const format = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "mp4" : "webm";
      return { audio: await base64(blob), format };
    },
    cancel: () => void finish(),
  };
}

async function base64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

/** Reads `text` aloud with the device's voice, in the page's language. */
export function readAloud(text: string): void {
  if (typeof speechSynthesis === "undefined" || !text.trim()) return;
  speechSynthesis.cancel();
  const said = new SpeechSynthesisUtterance(text);
  said.lang = navigator.language;
  speechSynthesis.speak(said);
}

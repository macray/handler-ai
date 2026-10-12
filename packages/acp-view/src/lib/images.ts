// Images in a prompt (ACP `image` content blocks): read from a paste, a drop or a file picker,
// made small enough for a model (the vendors downscale beyond ~1568 px anyway) and for the
// session's event log, where they are kept as they were sent. Shown with `imageSrc` (render.ts).
import { IMAGE_TYPES } from "./render";

export interface PromptImage {
  mimeType: string;
  data: string; // base64
}

/** What a person sends: text, images, or both. */
export interface Prompt {
  text: string;
  images: PromptImage[];
}

const MAX_EDGE = 1568;
const MAX_BYTES = 1_500_000; // above, a PNG becomes a JPEG
export const MAX_IMAGES = 5;

export function isImage(file: File): boolean {
  return file.type.startsWith("image/");
}

/** The image as it will be sent: as is when small enough and of a type every model takes (those
 *  shown, IMAGE_TYPES), else scaled down and re-encoded. */
export async function readImage(file: Blob): Promise<PromptImage> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  if (scale === 1 && IMAGE_TYPES.has(file.type) && file.size <= MAX_BYTES) {
    bitmap.close();
    return { mimeType: file.type, data: await base64(file) };
  }
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  let blob = await encode(canvas, "image/png");
  if (blob.size > MAX_BYTES) blob = await encode(canvas, "image/jpeg", 0.9);
  return { mimeType: blob.type, data: await base64(blob) };
}

function encode(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("not encoded"))), type, quality),
  );
}

function base64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

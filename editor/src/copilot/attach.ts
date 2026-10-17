// Reference image attached to the copilot composer: "generate variations like this image".
import type { Format } from "./flows";

export interface ReferenceImage { dataUrl: string; name: string; width: number; height: number }

const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_SIDE = 1536; // plenty for the vision read; keeps the request well under the API's 12 MB cap

/** Decode, downscale and re-encode as PNG (the backend reads references as PNG). */
export async function readReferenceImage(file: File): Promise<ReferenceImage> {
  if (!file.type.startsWith("image/")) throw new Error("That file isn't an image");
  if (file.size > MAX_FILE_BYTES) throw new Error("Image is too large (max 20 MB)");
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = () => rej(new Error("Couldn't read that image"));
      im.src = url;
    });
    const k = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
    const w = Math.max(1, Math.round(img.naturalWidth * k));
    const h = Math.max(1, Math.round(img.naturalHeight * k));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    canvas.getContext("2d")!.drawImage(img, 0, 0, w, h);
    return { dataUrl: canvas.toDataURL("image/png"), name: file.name || "image.png", width: img.naturalWidth, height: img.naturalHeight };
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** The ad format closest to the reference's aspect ratio. */
export function formatForAspect(width: number, height: number): Format {
  const r = width / Math.max(1, height);
  if (r >= 1.45) return "landscape";
  if (r >= 0.9) return "square";
  if (r <= 0.68) return "story";
  return "feed";
}

/** First image file in a paste / drop. */
export function imageFromTransfer(dt: DataTransfer | null): File | null {
  if (!dt) return null;
  for (const f of Array.from(dt.files ?? [])) if (f.type.startsWith("image/")) return f;
  for (const it of Array.from(dt.items ?? [])) {
    if (it.kind === "file" && it.type.startsWith("image/")) return it.getAsFile();
  }
  return null;
}

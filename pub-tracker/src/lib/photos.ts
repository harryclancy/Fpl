import imageCompression from 'browser-image-compression';

/** Full-size but web-reasonable version, stored for full-screen viewing. */
export async function compressForStorage(file: File | Blob): Promise<Blob> {
  return imageCompression(file as File, {
    maxWidthOrHeight: 1600,
    maxSizeMB: 0.9,
    initialQuality: 0.82,
    useWebWorker: true,
    fileType: 'image/webp',
  });
}

/** Small thumbnail used in grids/timelines so we never render full photos in lists. */
export async function makeThumbnail(file: File | Blob): Promise<Blob> {
  return imageCompression(file as File, {
    maxWidthOrHeight: 320,
    maxSizeMB: 0.12,
    initialQuality: 0.75,
    useWebWorker: true,
    fileType: 'image/webp',
  });
}

const urlCache = new WeakMap<Blob, string>();

/** Stable object URL per blob instance — avoids leaking a new URL on every render. */
export function blobUrl(blob: Blob): string {
  let url = urlCache.get(blob);
  if (!url) {
    url = URL.createObjectURL(blob);
    urlCache.set(blob, url);
  }
  return url;
}

export async function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

export async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const res = await fetch(dataUrl);
  return res.blob();
}

import type { ImageMetadata } from 'astro';

// Every capture image, keyed by the "assets/<file>" path used in products.json.
const all = import.meta.glob<ImageMetadata>('../../capture/assets/*.{png,jpg}', { eager: true, import: 'default' });

export function captureImage(path: string): ImageMetadata {
  const img = all[`../../capture/${path}`];
  if (!img) throw new Error(`Missing capture image: ${path}`);
  return img;
}

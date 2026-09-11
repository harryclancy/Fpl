export function combineRatings(a: number | null | undefined, b: number | null | undefined): number | null {
  const vals = [a, b].filter((v): v is number => typeof v === 'number');
  if (!vals.length) return null;
  return Math.round((vals.reduce((s, v) => s + v, 0) / vals.length) * 4) / 4;
}

export function formatRating(v: number | null | undefined): string {
  if (v == null) return '—';
  if (Number.isInteger(v)) return v.toFixed(0);
  if ((v * 4) % 1 === 0 && (v * 2) % 1 !== 0) return v.toFixed(2); // quarter step (e.g. combined)
  return v.toFixed(1);
}

export function ratingLabel(v: number | null | undefined): string {
  if (v == null) return 'Not rated';
  return `${v % 1 === 0 ? v : v.toFixed(2)} / 5`;
}

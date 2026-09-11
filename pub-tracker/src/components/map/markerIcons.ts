import L from 'leaflet';

function pinSvg(color: string, glyph: 'check' | 'dash' | 'heart' | 'bookmark'): string {
  const glyphMarkup: Record<string, string> = {
    check: '<path d="M6 10.5l2.5 2.5L14 7.5" stroke="white" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    dash: '<circle cx="10" cy="10" r="3" fill="white"/>',
    heart:
      '<path d="M10 14s-4.5-2.8-4.5-6.1C5.5 6 7 4.7 8.6 4.7c.9 0 1.7.4 2.2 1.1.5-.7 1.3-1.1 2.2-1.1 1.6 0 3.1 1.3 3.1 3.2C16.1 11.2 10 14 10 14z" fill="white"/>',
    bookmark: '<path d="M7 4.5h6v10l-3-2.3-3 2.3v-10z" fill="white"/>',
  };
  return `
  <svg width="30" height="40" viewBox="0 0 30 40" xmlns="http://www.w3.org/2000/svg">
    <path d="M15 0C6.7 0 0 6.7 0 15c0 10.5 15 25 15 25s15-14.5 15-25C30 6.7 23.3 0 15 0z" fill="${color}"/>
    <circle cx="15" cy="15" r="10.5" fill="${color}" stroke="white" stroke-width="1.5"/>
    <g transform="translate(5,5)">${glyphMarkup[glyph]}</g>
  </svg>`;
}

function makeIcon(color: string, glyph: 'check' | 'dash' | 'heart' | 'bookmark') {
  return L.divIcon({
    className: 'pub-marker-icon',
    html: pinSvg(color, glyph),
    iconSize: [30, 40],
    iconAnchor: [15, 40],
    popupAnchor: [0, -36],
  });
}

export const visitedIcon = makeIcon('#1c8a4b', 'check');
export const unvisitedIcon = makeIcon('#d97706', 'dash');
export const favouriteIcon = makeIcon('#d1435b', 'heart');
export const wantIcon = makeIcon('#6d5bd0', 'bookmark');

export function iconForPub(pub: { status: { visited: boolean; favouriteHarry: boolean; favouriteAva: boolean; wantToVisit: boolean } }) {
  if (pub.status.favouriteHarry || pub.status.favouriteAva) return favouriteIcon;
  if (pub.status.wantToVisit) return wantIcon;
  return pub.status.visited ? visitedIcon : unvisitedIcon;
}

export const userLocationIcon = L.divIcon({
  className: 'pub-marker-icon',
  html: `<div style="width:18px;height:18px;border-radius:50%;background:#2f7bc4;border:3px solid white;box-shadow:0 0 0 3px rgba(47,123,196,0.35)"></div>`,
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

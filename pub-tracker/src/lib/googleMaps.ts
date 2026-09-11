import type { LatLon } from './geo';

/** A pub-to-pub directions link (used by the two-pub compare tool and crawls). */
export function directionsBetween(from: LatLon, to: LatLon, mode: 'walking' | 'driving' = 'walking'): string {
  return `https://www.google.com/maps/dir/?api=1&origin=${from.lat},${from.lon}&destination=${to.lat},${to.lon}&travelmode=${mode}`;
}

/** Multi-stop directions link for a pub crawl (Google Maps supports waypoints). */
export function directionsForCrawl(points: LatLon[], mode: 'walking' | 'driving' = 'walking'): string | null {
  if (points.length < 2) return null;
  const origin = points[0];
  const destination = points[points.length - 1];
  const waypoints = points.slice(1, -1);
  const url = new URL('https://www.google.com/maps/dir/?api=1');
  url.searchParams.set('origin', `${origin.lat},${origin.lon}`);
  url.searchParams.set('destination', `${destination.lat},${destination.lon}`);
  if (waypoints.length) {
    url.searchParams.set('waypoints', waypoints.map((p) => `${p.lat},${p.lon}`).join('|'));
  }
  url.searchParams.set('travelmode', mode);
  return url.toString();
}

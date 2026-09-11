// Builds src/data/pubs.json from the raw OSM-derived Dublin pubs dataset.
//
// Source: irishshagua/dublin-pubs-map (MIT-style open GitHub project) — a
// community-maintained, geographically real list of Dublin pub names + coordinates
// derived from OpenStreetMap. We only keep verified real-world name + lat/lon pairs;
// we do NOT invent addresses, phone numbers, or opening hours. Area/district is a
// best-effort nearest-centroid approximation that the user can correct in-app.
//
// Re-run with: node scripts/build-pubs.mjs
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { DUBLIN_AREAS } from './dublin-areas.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const raw = JSON.parse(readFileSync(path.join(__dirname, 'raw-dublin-pubs.geojson'), 'utf-8'));

// Roughly the Dublin city + county bounding box. A couple of stray points in the
// source dataset fall in Scotland (clearly mis-entered) — excluded here.
const BOUNDS = { minLat: 53.15, maxLat: 53.65, minLon: -6.6, maxLon: -6.0 };

function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371; // km
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function nearestArea(lat, lon) {
  let best = null;
  let bestDist = Infinity;
  for (const area of DUBLIN_AREAS) {
    const d = haversine(lat, lon, area.lat, area.lon);
    if (d < bestDist) {
      bestDist = d;
      best = area;
    }
  }
  return best;
}

function slugify(str) {
  return str
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}

function googleMapsUrl(name, lat, lon) {
  // A search query biased to the pub's real coordinates resolves reliably to the
  // correct venue without needing a Places API key.
  const q = encodeURIComponent(`${name} pub, ${lat},${lon}`);
  return `https://www.google.com/maps/search/?api=1&query=${q}`;
}

function directionsUrl(lat, lon) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=walking`;
}

const points = raw.features.filter((f) => f.geometry && f.geometry.type === 'Point');

const seen = new Map(); // dedupe key -> pub
let skippedOutOfBounds = 0;
let dedupedCount = 0;

const pubs = [];

for (const f of points) {
  const [lon, lat] = f.geometry.coordinates;
  const name = (f.properties.name || '').trim();
  if (!name) continue;
  if (lat < BOUNDS.minLat || lat > BOUNDS.maxLat || lon < BOUNDS.minLon || lon > BOUNDS.maxLon) {
    skippedOutOfBounds++;
    continue;
  }

  // Dedupe near-identical entries (same normalised name within ~60m of each other).
  const normName = name.toLowerCase().replace(/[^a-z0-9]/g, '');
  let isDupe = false;
  for (const existing of pubs) {
    if (existing._normName === normName && haversine(lat, lon, existing.lat, existing.lon) < 0.06) {
      isDupe = true;
      break;
    }
  }
  if (isDupe) {
    dedupedCount++;
    continue;
  }

  const area = nearestArea(lat, lon);
  const id = slugify(name) + '-' + slugify(area.name);
  // Ensure id uniqueness
  let finalId = id;
  let n = 2;
  while (seen.has(finalId)) {
    finalId = `${id}-${n++}`;
  }
  seen.set(finalId, true);

  pubs.push({
    id: finalId,
    _normName: normName,
    name,
    lat,
    lon,
    area: area.name,
    district: area.district,
    region: area.region,
    address: null,
    phone: null,
    website: null,
    openingHours: null,
    tags: ['pub'],
    image: null,
    source: 'osm-community',
    googleMapsUrl: googleMapsUrl(name, lat, lon),
    directionsUrl: directionsUrl(lat, lon),
    createdAt: new Date().toISOString(),
  });
}

for (const p of pubs) delete p._normName;

pubs.sort((a, b) => a.name.localeCompare(b.name));

const outDir = path.join(__dirname, '..', 'src', 'data');
writeFileSync(path.join(outDir, 'pubs.json'), JSON.stringify(pubs, null, 2));

console.log(`Built ${pubs.length} pubs.`);
console.log(`Skipped out-of-bounds: ${skippedOutOfBounds}`);
console.log(`Deduped near-identical: ${dedupedCount}`);

const districtCounts = {};
for (const p of pubs) districtCounts[p.district] = (districtCounts[p.district] || 0) + 1;
console.log('By district:', districtCounts);

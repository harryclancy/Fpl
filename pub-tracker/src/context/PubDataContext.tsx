import { createContext, useContext, useMemo, useState, useCallback, type ReactNode } from 'react';
import { useLiveQuery } from 'dexie-react-hooks';
import { db } from '../db/database';
import rawPubs from '../data/pubs.json';
import type { Pub, PubWithComputed, Review } from '../types';
import { combineRatings } from '../lib/rating';
import { haversineKm } from '../lib/geo';

const STATIC_PUBS = rawPubs as Pub[];

type LocationStatus = 'idle' | 'requesting' | 'granted' | 'denied' | 'unavailable';

interface PubDataContextValue {
  pubs: PubWithComputed[];
  pubsById: Map<string, PubWithComputed>;
  visitCounts: Map<string, number>;
  areas: string[];
  districts: string[];
  loading: boolean;
  userLocation: { lat: number; lon: number } | null;
  locationStatus: LocationStatus;
  locationError: string | null;
  requestLocation: () => void;
}

const PubDataContext = createContext<PubDataContextValue | null>(null);

const LOCATION_STORAGE_KEY = 'dpt.lastLocation';

export function PubDataProvider({ children }: { children: ReactNode }) {
  const [locationStatus, setLocationStatus] = useState<LocationStatus>('idle');
  const [locationError, setLocationError] = useState<string | null>(null);
  const [userLocation, setUserLocation] = useState<{ lat: number; lon: number } | null>(() => {
    try {
      const raw = localStorage.getItem(LOCATION_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });

  const requestLocation = useCallback(() => {
    if (!('geolocation' in navigator)) {
      setLocationStatus('unavailable');
      setLocationError('Location is not supported on this device.');
      return;
    }
    setLocationStatus('requesting');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const loc = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        setUserLocation(loc);
        setLocationStatus('granted');
        setLocationError(null);
        try {
          localStorage.setItem(LOCATION_STORAGE_KEY, JSON.stringify(loc));
        } catch {
          /* ignore quota errors */
        }
      },
      (err) => {
        setLocationStatus('denied');
        setLocationError(err.message || 'Could not get your location.');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  }, []);

  const statuses = useLiveQuery(() => db.statuses.toArray(), [], []);
  const reviews = useLiveQuery(() => db.reviews.toArray(), [], []);
  const edits = useLiveQuery(() => db.edits.toArray(), [], []);
  const visits = useLiveQuery(() => db.visits.toArray(), [], []);

  const loading = statuses === undefined || reviews === undefined || edits === undefined || visits === undefined;

  const visitCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const v of visits ?? []) {
      map.set(v.pubId, (map.get(v.pubId) ?? 0) + 1);
    }
    return map;
  }, [visits]);

  const pubs = useMemo<PubWithComputed[]>(() => {
    const statusMap = new Map((statuses ?? []).map((s) => [s.pubId, s]));
    const editMap = new Map((edits ?? []).map((e) => [e.pubId, e]));
    const reviewMap = new Map<string, Review>();
    for (const r of reviews ?? []) reviewMap.set(`${r.pubId}:${r.person}`, r);

    return STATIC_PUBS.map((pub) => {
      const status = statusMap.get(pub.id) ?? {
        pubId: pub.id,
        visited: false,
        firstVisitDate: null,
        favouriteHarry: false,
        favouriteAva: false,
        wantToVisit: false,
        updatedAt: pub.createdAt,
      };
      const edit = editMap.get(pub.id) ?? null;
      const harryReview = reviewMap.get(`${pub.id}:harry`) ?? null;
      const avaReview = reviewMap.get(`${pub.id}:ava`) ?? null;
      const distanceKm = userLocation ? haversineKm(userLocation, { lat: pub.lat, lon: pub.lon }) : null;

      return {
        ...pub,
        status,
        edit,
        harryReview,
        avaReview,
        combinedRating: combineRatings(harryReview?.rating, avaReview?.rating),
        visitCount: visitCounts.get(pub.id) ?? 0,
        distanceKm,
        displayName: edit?.name || pub.name,
        displayArea: edit?.area || pub.area,
        displayAddress: edit?.address || pub.address,
        displayImage: edit?.imageOverride || pub.image,
      };
    });
  }, [statuses, edits, reviews, userLocation, visitCounts]);

  const pubsById = useMemo(() => new Map(pubs.map((p) => [p.id, p])), [pubs]);

  const areas = useMemo(() => Array.from(new Set(pubs.map((p) => p.displayArea))).sort(), [pubs]);
  const districts = useMemo(() => Array.from(new Set(pubs.map((p) => p.district))).sort(), [pubs]);

  const value: PubDataContextValue = {
    pubs,
    pubsById,
    visitCounts,
    areas,
    districts,
    loading,
    userLocation,
    locationStatus,
    locationError,
    requestLocation,
  };

  return <PubDataContext.Provider value={value}>{children}</PubDataContext.Provider>;
}

export function usePubData(): PubDataContextValue {
  const ctx = useContext(PubDataContext);
  if (!ctx) throw new Error('usePubData must be used within PubDataProvider');
  return ctx;
}

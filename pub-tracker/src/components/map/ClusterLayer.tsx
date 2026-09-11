import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet.markercluster';
import type { PubWithComputed } from '../../types';
import { iconForPub } from './markerIcons';

interface ClusterLayerProps {
  pubs: PubWithComputed[];
  onMarkerClick: (pub: PubWithComputed) => void;
}

/** Renders hundreds of pub markers efficiently via leaflet.markercluster, wired
 * imperatively since react-leaflet has no first-party clustering component. */
export function ClusterLayer({ pubs, onMarkerClick }: ClusterLayerProps) {
  const map = useMap();
  const groupRef = useRef<L.MarkerClusterGroup | null>(null);
  const clickHandlerRef = useRef(onMarkerClick);
  useEffect(() => {
    clickHandlerRef.current = onMarkerClick;
  }, [onMarkerClick]);

  useEffect(() => {
    const group = L.markerClusterGroup({
      chunkedLoading: true,
      maxClusterRadius: 50,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      iconCreateFunction: (cluster) => {
        const markers = cluster.getAllChildMarkers() as (L.Marker & { pubStatus?: string })[];
        const visitedCount = markers.filter((m) => m.pubStatus === 'visited').length;
        const total = markers.length;
        const allVisited = visitedCount === total;
        const noneVisited = visitedCount === 0;
        const color = allVisited ? '#1c8a4b' : noneVisited ? '#d97706' : '#8a7a3f';
        return L.divIcon({
          html: `<div style="background:${color};color:white;width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;border:2.5px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.25)">${total}</div>`,
          className: 'pub-cluster-icon',
          iconSize: [38, 38],
        });
      },
    });
    groupRef.current = group;
    map.addLayer(group);
    return () => {
      map.removeLayer(group);
      groupRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    const group = groupRef.current;
    if (!group) return;
    group.clearLayers();
    const markers = pubs.map((pub) => {
      const marker = L.marker([pub.lat, pub.lon], { icon: iconForPub(pub) }) as L.Marker & { pubStatus?: string };
      marker.pubStatus = pub.status.visited ? 'visited' : 'unvisited';
      marker.on('click', () => clickHandlerRef.current(pub));
      return marker;
    });
    group.addLayers(markers);
  }, [pubs]);

  return null;
}

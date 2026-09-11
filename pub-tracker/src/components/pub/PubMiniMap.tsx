import { MapContainer, Marker, TileLayer } from 'react-leaflet';
import { iconForPub } from '../map/markerIcons';
import type { PubWithComputed } from '../../types';

export function PubMiniMap({ pub }: { pub: PubWithComputed }) {
  return (
    <div className="h-40 w-full overflow-hidden rounded-card shadow-card">
      <MapContainer
        center={[pub.lat, pub.lon]}
        zoom={16}
        scrollWheelZoom={false}
        dragging={false}
        zoomControl={false}
        doubleClickZoom={false}
        touchZoom={false}
        attributionControl={false}
        className="h-full w-full"
      >
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <Marker position={[pub.lat, pub.lon]} icon={iconForPub(pub)} />
      </MapContainer>
    </div>
  );
}

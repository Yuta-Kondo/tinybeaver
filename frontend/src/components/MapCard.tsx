import type { GeoLocation } from "../lib/api";

interface Props {
  location: GeoLocation;
}

export default function MapCard({ location }: Props) {
  const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(location.query ?? location.name ?? location.address)}`;

  return (
    <a
      className="map-chip"
      href={mapsUrl}
      target="_blank"
      rel="noopener noreferrer"
    >
      <svg className="map-chip-icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M8 1.5A4.5 4.5 0 0 0 3.5 6c0 3 4.5 8.5 4.5 8.5S12.5 9 12.5 6A4.5 4.5 0 0 0 8 1.5Z" fill="currentColor" fillOpacity="0.2" stroke="currentColor" strokeWidth="1.2"/>
        <circle cx="8" cy="6" r="1.5" fill="currentColor"/>
      </svg>
      <span className="map-chip-name">{location.name ?? location.address}</span>
      <span className="map-chip-arrow">↗</span>
    </a>
  );
}

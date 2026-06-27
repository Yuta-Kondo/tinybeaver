import { useEffect, useRef } from "react";
import type { GeoLocation } from "../lib/api";

let leafletLoaded = false;

interface Props {
  location: GeoLocation;
}

export default function MapCard({ location }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    import("leaflet").then((L) => {
      if (!containerRef.current || mapRef.current) return;

      if (!leafletLoaded) {
        delete (L.Icon.Default.prototype as any)._getIconUrl;
        L.Icon.Default.mergeOptions({
          iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
          iconUrl:       "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
          shadowUrl:     "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
        });
        leafletLoaded = true;
      }

      const map = L.map(containerRef.current!, {
        center: [location.lat, location.lng],
        zoom: 15,
        zoomControl: false,
        scrollWheelZoom: false,
        attributionControl: false,
        dragging: false,
      });

      L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        { subdomains: "abcd", maxZoom: 20 }
      ).addTo(map);

      const icon = L.divIcon({
        className: "",
        html: `<div class="map-pin"></div>`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      });

      L.marker([location.lat, location.lng], { icon }).addTo(map);
      mapRef.current = map;
    });

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [location.lat, location.lng]);

  // q=lat,lng drops an exact pin; label= shows the place name in the info card
  const googleUrl = `https://www.google.com/maps?q=${location.lat},${location.lng}&label=${encodeURIComponent(location.address)}`;

  // Short label: first two comma-separated parts of the display name
  const shortLabel = location.display_name
    ? location.display_name.split(",").slice(0, 2).join(",").trim()
    : location.address;

  return (
    <div className="map-card">
      <div className="map-card-header">
        <svg className="map-card-pin-icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M8 1.5A4.5 4.5 0 0 0 3.5 6c0 3 4.5 8.5 4.5 8.5S12.5 9 12.5 6A4.5 4.5 0 0 0 8 1.5Z" fill="currentColor" fill-opacity="0.15" stroke="currentColor" stroke-width="1.2"/>
          <circle cx="8" cy="6" r="1.5" fill="currentColor"/>
        </svg>
        <span className="map-card-address">{shortLabel}</span>
        <a className="map-card-open" href={googleUrl} target="_blank" rel="noopener noreferrer">
          Open in Maps ↗
        </a>
      </div>
      <a href={googleUrl} target="_blank" rel="noopener noreferrer" className="map-card-body-link">
        <div className="map-card-body" ref={containerRef} />
        <div className="map-card-overlay">
          <span className="map-card-overlay-label">View on Google Maps</span>
        </div>
      </a>
    </div>
  );
}

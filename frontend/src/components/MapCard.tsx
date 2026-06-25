import { useEffect, useRef } from "react";
import type { GeoLocation } from "../lib/api";

// Dynamically import leaflet to avoid SSR issues and fix default icon paths
let leafletLoaded = false;

interface Props {
  location: GeoLocation;
}

export default function MapCard({ location }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    // Leaflet needs to be imported dynamically because it touches `window`
    import("leaflet").then((L) => {
      if (!containerRef.current || mapRef.current) return;

      if (!leafletLoaded) {
        // Fix default marker icons (bundler strips the default path resolution)
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

      // CartoDB Dark Matter tiles — matches our dark UI
      L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        { subdomains: "abcd", maxZoom: 20 }
      ).addTo(map);

      // Emerald-tinted custom marker
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

  const googleUrl = `https://maps.google.com/?q=${location.lat},${location.lng}`;

  return (
    <div className="map-card">
      <div className="map-card-header">
        <span className="map-card-address">📍 {location.address}</span>
        <a className="map-card-open" href={googleUrl} target="_blank" rel="noopener noreferrer">
          Open in Maps ↗
        </a>
      </div>
      <div className="map-card-body" ref={containerRef} />
    </div>
  );
}

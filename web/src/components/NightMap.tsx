// The night map (docs/LLD.md, section 15): the user as a pulsing blue dot, the search
// ring, a sweep while searching, and providers as glowing dots that appear best first.
// Leaflet with Esri's dark gray canvas (base plus place names): no key needed, only the
// credit line. CARTO's dark tiles were the first choice but now ask for a key.

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export interface MapPin {
  id: string;
  name: string;
  lat: number;
  lng: number;
}

interface Props {
  center: { lat: number; lng: number };
  radiusKm: number;
  pins: MapPin[];
  marked: string[];          // the ones to be called (marigold ring)
  focused: string | null;    // the one whose card is highlighted
  searching: boolean;
  onFocus?: (id: string) => void;
}

const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
const BASE = `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`;
const LABELS = `${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`;
const CREDIT = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors";
const APPEAR_MS = 280; // the gap between dots appearing

function pinIcon(marked: boolean, focused: boolean, rank: number) {
  const cls = ["pin", marked ? "marked" : "", focused ? "focused" : ""].join(" ");
  return L.divIcon({ className: "", html: `<div class="${cls}"><span>${rank}</span></div>`, iconSize: [28, 28], iconAnchor: [14, 14] });
}

export function NightMap({ center, radiusKm, pins, marked, focused, searching, onFocus }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const ring = useRef<L.Circle | null>(null);
  const markers = useRef(new Map<string, L.Marker>());
  const shown = useRef(new Set<string>());

  // The map, the user's dot and the ring.
  useEffect(() => {
    if (!box.current) return;
    const m = L.map(box.current, { zoomControl: false, attributionControl: true }).setView([center.lat, center.lng], 13);
    L.tileLayer(BASE, { attribution: CREDIT, maxZoom: 16 }).addTo(m);
    L.tileLayer(LABELS, { maxZoom: 16, opacity: 0.8 }).addTo(m);
    L.marker([center.lat, center.lng], {
      icon: L.divIcon({ className: "", html: '<div class="me"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }),
      interactive: false, zIndexOffset: 1000,
    }).addTo(m);
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      ring.current = null;
      markers.current.clear();
      shown.current.clear();
    };
  }, [center.lat, center.lng]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    ring.current?.remove();
    ring.current = L.circle([center.lat, center.lng], {
      radius: radiusKm * 1000, color: "#f5a524", weight: 1.5, opacity: 0.6, dashArray: "6 8", fill: true,
      fillColor: "#f5a524", fillOpacity: 0.03, interactive: false,
    }).addTo(m);
    m.fitBounds(ring.current.getBounds(), { padding: [12, 12] });
  }, [center.lat, center.lng, radiusKm]);

  // Providers appear one by one, best first; later renders only restyle them.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const timers: number[] = [];
    pins.forEach((pin, i) => {
      const icon = pinIcon(marked.includes(pin.id), focused === pin.id, i + 1);
      const existing = markers.current.get(pin.id);
      if (existing) {
        existing.setIcon(icon);
        return;
      }
      const add = () => {
        const marker = L.marker([pin.lat, pin.lng], { icon, title: pin.name, riseOnHover: true }).addTo(m);
        marker.on("click", () => onFocus?.(pin.id));
        markers.current.set(pin.id, marker);
        shown.current.add(pin.id);
      };
      timers.push(window.setTimeout(add, shown.current.size === 0 ? (i + 1) * APPEAR_MS : 0));
    });
    return () => timers.forEach(clearTimeout);
  }, [pins, marked, focused, onFocus]);

  return (
    <div className="map-wrap">
      <div ref={box} className="map" role="img" aria-label="Map of providers near you" />
      {searching && <div className="sweep" aria-hidden="true" />}
    </div>
  );
}

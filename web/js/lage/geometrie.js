// ------------------------------------------------------------------ Geometrie
export function circle(lat, lon, km, n = 128) {
  const R = 6371.0088, d = km / R, la = (lat * Math.PI) / 180, lo = (lon * Math.PI) / 180, ring = [];
  for (let i = 0; i <= n; i++) {
    const b = (i / n) * 2 * Math.PI;
    const la2 = Math.asin(Math.sin(la) * Math.cos(d) + Math.cos(la) * Math.sin(d) * Math.cos(b));
    const lo2 = lo + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(la), Math.cos(d) - Math.sin(la) * Math.sin(la2));
    ring.push([(lo2 * 180) / Math.PI, (la2 * 180) / Math.PI]);
  }
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } };
}

// Vignette: oberste Kartenebene, Schwarz. Ab dem Radius steigt die Deckkraft stufenlos (Smoothstep) von 0 auf 1, bei Radius + VIG_FADE_KM
// ist nichts mehr zu sehen. Gebaut aus schmalen Ringen (je ~0,15 km) mit eigener Deckkraft, dahinter eine volle schwarze Fläche.
export const VIG_FADE_KM = 30, VIG_RINGS = 200, VIG_ID = 'vig';
export function vignette(lat, lon, km) {
  const world = [[-179.9, -85], [179.9, -85], [179.9, 85], [-179.9, 85], [-179.9, -85]];
  const ring = (r) => circle(lat, lon, r, 96).geometry.coordinates[0];
  const feats = [];
  let inner = ring(km);
  for (let k = 0; k < VIG_RINGS; k++) {
    const outer = ring(km + ((k + 1) / VIG_RINGS) * VIG_FADE_KM);
    const t = (k + 0.5) / VIG_RINGS;
    feats.push({ type: 'Feature', properties: { a: t * t * (3 - 2 * t) }, geometry: { type: 'Polygon', coordinates: [outer, inner] } });
    inner = outer;
  }
  feats.push({ type: 'Feature', properties: { a: 1 }, geometry: { type: 'Polygon', coordinates: [world, inner] } });
  return { type: 'FeatureCollection', features: feats };
}
// Unsichtbarer Anker: darunter liegen Basiskarte, Relief und Regenradar, darüber die Datenebenen (die Vignette liegt über allem)
export const baseAnchor = () => 'radius-fill';

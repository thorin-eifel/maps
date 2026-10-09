// Zeichenerklärung der Karte: Abschnitte je aktiver Ebene (Regenradar, Wind, Blitze, Verkehr, Luftverkehr) in einem Overlay unten rechts.
// Regenskala: Farben und Klassengrenzen wie in der Legende des DWD-Layers dwd:Niederschlagsradar (GetLegendGraphic, geprüft 2026-09-30).
// Farben werden per CSSOM gesetzt (die CSP verbietet Inline-Styles im Markup).
export const RAIN_SCALE = [
  ['0,1 bis 0,2', '#33FFFF'], ['0,2 bis 0,4', '#1ACC9A'], ['0,4 bis 1', '#019934'], ['1 bis 2', '#4DB31B'], ['2 bis 3', '#99CC01'],
  ['3 bis 5', '#CCE601'], ['5 bis 7,5', '#FFFF01'], ['7,5 bis 10', '#FFC401'], ['10 bis 15', '#FF8901'], ['15 bis 30', '#FF4501'],
  ['30 bis 45', '#FE0000'], ['45 bis 75', '#E5004C'], ['75 bis 100', '#CC0098'], ['100 bis 150', '#6600CB'], ['über 150', '#0000FE'],
];
// Beschriftung an ausgewählten Klassen (Anfangswert der Klasse, Spalte im Raster)
const RAIN_TICKS = [['0,1', 0], ['1', 3], ['5', 6], ['10', 8], ['30', 10], ['75', 12], ['150', 14]];

export function buildRainLegend(strip, labels) {
  if (!strip || !labels) return;
  strip.replaceChildren(); labels.replaceChildren();
  for (const [label, color] of RAIN_SCALE) {
    const c = document.createElement('span');
    c.className = 'rain-cell'; c.style.background = color; c.title = `${label} mm/h`;
    strip.append(c);
  }
  for (const [text, col] of RAIN_TICKS) {
    const t = document.createElement('span');
    t.textContent = text; t.style.gridColumn = `${col + 1} / span 2`;
    labels.append(t);
  }
}

/** Abschnitte je Ebene ein- und ausblenden; das Overlay zeigt sich nur, wenn mindestens ein Abschnitt aktiv ist. */
export function updateLegend(root, active) {
  if (!root) return;
  let any = false;
  for (const sec of root.querySelectorAll('section[data-legend]')) {
    const on = !!active[sec.dataset.legend];
    sec.hidden = !on; any = any || on;
  }
  root.hidden = !any;
}

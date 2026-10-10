import { cssColor } from '../util.js';

// ------------------------------------------------------------------ Farben
export function palette() {
  return {
    bg: cssColor('--surface'), line: cssColor('--border-strong'), fg: cssColor('--fg'), muted: cssColor('--fg-muted'),
    critical: cssColor('--brand-red-600'), warning: 'rgb(230,130,30)', notice: cssColor('--sys-yellow'),
    // Verkehr: feste Signalfarben, unabhängig vom Farbschema
    yellow: '#f5c400', orange: '#f28c1a', red: '#d62828', black: '#111111',
    info: cssColor('--sys-blue'), accent: cssColor('--accent'), white: '#fff', ink: cssColor('--fg'), bg: cssColor('--bg-elevated'),
  };
}
// Verkehrsmeldungen tragen zusätzlich `lvl` (yellow/orange/red/black, siehe trafficLevel), alles andere die Stufe `severity`
export const sevColor = (c, key = null) => ['match', key ? ['get', key] : ['coalesce', ['get', 'lvl'], ['get', 'severity']], 'critical', c.critical, 'warning', c.warning, 'notice', c.notice,
  'yellow', c.yellow, 'orange', c.orange, 'red', c.red, 'black', c.black, c.info];

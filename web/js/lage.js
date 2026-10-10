// Lagekarte: Einstieg. Die Teile liegen unter js/lage/ (Zustand, Karte, Basiskarte, Ebenenmenü, Panels, Laden, Prüfzugang).
// Reihenfolge beim Start: Bedienung verdrahten, Metadaten holen, Karte bauen, Daten laden.
import { $, getJSON } from './util.js';
import { state } from './lage/zustand.js';
import { wire } from './lage/ebenen.js';
import { setupSideToggle } from './lage/panels.js';
import { initMap } from './lage/karte.js';
import { refresh } from './lage/laden.js';

if (location.hash === '#debug') {   // Prüfhilfe: Fehler der Seite in ein Attribut schreiben, weil die Konsole nicht überall lesbar ist
  const note = (m) => { document.documentElement.dataset.debugErr = `${document.documentElement.dataset.debugErr ?? ''}${m}\n`.slice(-1500); };
  window.addEventListener('error', (e) => note(`${e.message} @${e.lineno}`));
  window.addEventListener('unhandledrejection', (e) => note(`rej: ${e.reason?.stack ?? e.reason}`));
}

async function main() {
  wire();
  try { state.meta = await getJSON('data/meta.json'); } catch { $('#apidown').hidden = false; return; }
  setupSideToggle();
  await initMap();
  await refresh();
}
main();

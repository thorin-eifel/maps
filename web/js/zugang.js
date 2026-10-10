// Zugangsdaten je Quelle (API-Schlüssel, Benutzername, Passwort). Nur in der Desktop-App: dort antwortet api/zugang.
// Auf dem statischen Webspace gibt es die Schnittstelle nicht, dann bleibt alles unsichtbar. Werte gehen nur an den lokalen Dienst
// und kommen nie zurück; die Seite erfährt nur "gesetzt" oder "nicht gesetzt".
import { h } from './util.js';

export async function ladeZugang() {
  try {
    const r = await fetch('api/zugang', { cache: 'no-store' });
    if (!r.ok) return null;
    const j = await r.json();
    return new Map((j.quellen ?? []).map((q) => [q.source_id, q]));
  } catch { return null; }
}

async function senden(body) {
  const r = await fetch('api/zugang', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-OSINT': '1' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Fehler ${r.status}`);
  return j;
}

const ART = { schluessel: 'Schlüssel', benutzername: 'Benutzername', passwort: 'Passwort' };

/** Eingabefelder für die Zugangsdaten einer Quelle. `q` kommt von api/zugang: { source_id, name, felder: [{ env, art, bezeichnung, gesetzt }] }. */
export function zugangBox(q) {
  const status = h('p', { class: 'zugang-status muted', role: 'status' });
  const form = h('form', { class: 'zugang', autocomplete: 'off', 'aria-label': `Zugangsdaten ${q.name}` });
  const zeilen = new Map();

  const zeige = (felder) => {
    for (const f of felder) {
      const z = zeilen.get(f.env);
      if (!z) continue;
      z.badge.textContent = f.gesetzt ? 'gesetzt' : 'nicht gesetzt';
      z.badge.className = `badge ${f.gesetzt ? 'st-ok' : 'st-stale'}`;
      z.input.placeholder = f.gesetzt ? 'zum Ändern neu eingeben' : '';
      z.entfernen.hidden = !f.gesetzt;
    }
  };

  for (const f of q.felder) {
    const id = `zg-${q.source_id}-${f.env}`;
    const input = h('input', { id, name: f.env, type: f.art === 'benutzername' ? 'text' : 'password', autocomplete: f.art === 'passwort' ? 'new-password' : 'off', spellcheck: 'false', maxlength: '256' });
    const badge = h('span');
    const entfernen = h('button', { class: 'btn', type: 'button' }, 'Entfernen');
    entfernen.addEventListener('click', async () => {
      try { zeige((await senden({ env: f.env, loeschen: true })).quellen.find((x) => x.source_id === q.source_id)?.felder ?? []); input.value = ''; status.textContent = `${f.bezeichnung} entfernt.`; }
      catch (err) { status.textContent = `Nicht entfernt: ${err.message}`; }
    });
    zeilen.set(f.env, { input, badge, entfernen });
    form.append(h('div', { class: 'zugang-zeile' }, h('label', { for: id }, `${f.bezeichnung} (${ART[f.art] ?? f.art})`), input, badge, entfernen));
  }

  form.append(h('button', { class: 'btn', type: 'submit' }, 'Speichern'));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    let n = 0;
    try {
      for (const f of q.felder) {
        const z = zeilen.get(f.env);
        if (!z.input.value.trim()) continue;
        const j = await senden({ env: f.env, wert: z.input.value });
        z.input.value = '';
        zeige(j.quellen.find((x) => x.source_id === q.source_id)?.felder ?? []);
        n++;
      }
      status.textContent = n ? 'Gespeichert. Gilt ab dem nächsten Abruf dieser Quelle.' : 'Nichts eingegeben.';
    } catch (err) { status.textContent = `Nicht gespeichert: ${err.message}`; }
  });
  zeige(q.felder);
  return h('div', { class: 'zugang-box' }, h('h3', {}, 'Zugangsdaten'), form, status,
    h('p', { class: 'muted klein' }, 'Nur in der Desktop-App. Die Werte liegen als Datei im Datenordner (nur für dich lesbar, nicht im Schlüsselbund) und gehen nur an diese Quelle.'));
}

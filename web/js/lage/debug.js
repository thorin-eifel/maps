import { applyLight } from './basiskarte.js';
import { light, map, ripples, state } from './zustand.js';
import { zellenWarten } from './zellenlauf.js';

// Prüfzugang (nur mit #debug in der Adresse): Ereignis 'osint-debug', Auftrag als JSON in <html data-debug-in>: {jump:[lng,lat,zoom], layer:'id'} setzt die Ansicht und
// schreibt Zählwerte der gezeichneten Objekte nach <html data-debug-out>. Kein eval, keine Daten nach außen.
export function debugHook(m) {
  document.addEventListener('osint-debug', async (e) => {
    const cmd = JSON.parse(document.documentElement.dataset.debugIn || '{}');
    if (cmd.jump) { m.jumpTo({ center: [cmd.jump[0], cmd.jump[1]], zoom: cmd.jump[2] }); await new Promise((r) => { m.once('idle', r); setTimeout(r, 6000); }); }
    if (cmd.zellen && state.zellen) await zellenWarten();
    const out = { zoom: m.getZoom() };
    if (cmd.zellen) { // Zellenbetrieb: gehaltene Zellen, Fehler, Anzahl gezeichneter Ereignisse und Dichtepunkte
      out.zellen = state.zellen ? { ...state.zellen.status(), version: state.zellen.version, events: state.events.length, base: state.base.length, band: state.base.some((f) => f.properties.stub) ? 'stubs' : 'zellen' } : 'aus';
    }
    for (const id of cmd.layers ?? []) out[id] = m.getLayer(id) ? m.queryRenderedFeatures({ layers: [id] }).length : 'fehlt';
    for (const im of cmd.images ?? []) out[`img:${im}`] = m.hasImage(im);
    for (const id of cmd.vis ?? []) out[`vis:${id}`] = m.getLayer(id) ? m.getLayoutProperty(id, 'visibility') : 'fehlt';
    if (cmd.order) out.order = m.getStyle().layers.map((l) => l.id).filter((id) => new RegExp(cmd.order).test(id)).join(',');
    if (cmd.paint) out.paint = cmd.paint.map((p) => `${p[0]}.${p[1]}=${JSON.stringify(m.getPaintProperty(p[0], p[1]))}`);
    if (cmd.cliffs) { // Hilfsabfrage: längste Klippenlinien im geladenen Bereich (Anfangspunkt)
      const found = new Map();
      for (const f of m.querySourceFeatures('basemap', { sourceLayer: 'earth', filter: ['==', 'kind', 'cliff'] })) {
        const l = f.geometry.type === 'LineString' ? f.geometry.coordinates : f.geometry.coordinates?.[0];
        if (l?.length) found.set(l[0].map((v) => +v.toFixed(4)).join(','), l.length);
      }
      out.cliffs = [...found.entries()].sort((x, y) => y[1] - x[1]).slice(0, 6);
    }
    if (cmd.perf) { // Messung: Bildintervall (ms) bei Dauer-Neuzeichnen, je Layergruppe ausgeblendet. Auftrag: {groups:{name:'regex'}, frames:90}
      const frames = cmd.perf.frames ?? 90, all = m.getStyle().layers.map((l) => l.id), res = {};
      const run = () => new Promise((resolve) => {
        const dts = []; let last = performance.now(), n = 0;
        const step = (t) => { dts.push(t - last); last = t; m.setBearing((n % 2) * 0.02); if (++n < frames) requestAnimationFrame(step); else { dts.shift(); dts.sort((a, b) => a - b); resolve({ mean: +(dts.reduce((a, b) => a + b, 0) / dts.length).toFixed(1), p95: +dts[Math.floor(dts.length * 0.95)].toFixed(1) }); } };
        requestAnimationFrame(step);
      });
      res.alle = await run();
      for (const [name, rx] of Object.entries(cmd.perf.groups ?? {})) {
        const ids = all.filter((id) => new RegExp(rx).test(id) && m.getLayoutProperty(id, 'visibility') !== 'none');
        for (const id of ids) m.setLayoutProperty(id, 'visibility', 'none');
        res[`ohne ${name} (${ids.length})`] = await run();
        for (const id of ids) m.setLayoutProperty(id, 'visibility', 'visible');
      }
      m.setBearing(0); out.perf = res;
    }
    if (cmd.licht) { // Prüfzugang: Licht setzen und Zustand lesen ({on, lon, lat, hoehe})
      if (cmd.licht.rebuild) light?.rebuildFields();
      if (cmd.licht.on !== undefined) { state.layers.licht = !!cmd.licht.on; const cb = document.querySelector('input[data-layer="licht"]'); if (cb) cb.checked = !!cmd.licht.on; applyLight(); }
      if (cmd.licht.px) { const ll = map.unproject(cmd.licht.px); light?.setLight(ll.lng, ll.lat); }
      if (cmd.licht.lon !== undefined) light?.setLight(cmd.licht.lon, cmd.licht.lat);
      if (cmd.licht.hoehe) light?.setHeight(cmd.licht.hoehe);
      await light?.refresh(); await new Promise((r) => setTimeout(r, 300));
      out.licht = light?.stats();
    }
    if (cmd.probe) { // Hilfsabfrage: Flächenarten unter dem Bildmittelpunkt
      const pt = m.project(m.getCenter()), ids = ['bm-water', 'bm-land-forest'].filter((i) => m.getLayer(i));
      out.probe = m.queryRenderedFeatures([[pt.x - 3, pt.y - 3], [pt.x + 3, pt.y + 3]], { layers: ids }).map((f) => `${f.layer.id}:${f.properties.kind ?? ''}`);
    }
    if (cmd.inscribe) { // Hilfsabfrage: Punkt größten Abstands zum Ufer in der Bildmitte (Gitter 10 px), für Zeichen in Seen
      const cv = m.getCanvas(), w = cv.clientWidth, hgt = cv.clientHeight, st = 10, nx = Math.floor(w / st), ny = Math.floor(hgt / st), cx = w / 2, cy = hgt / 2;
      const water = [];
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) water.push(m.queryRenderedFeatures([i * st + st / 2, j * st + st / 2], { layers: [cmd.inscribe] }).length > 0);
      let best = null;
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
        if (!water[j * nx + i]) continue;
        let dmin = 1e9;
        for (let b = 0; b < ny; b++) for (let a = 0; a < nx; a++) if (!water[b * nx + a]) { const d = (a - i) ** 2 + (b - j) ** 2; if (d < dmin) dmin = d; }
        const far = Math.hypot(i * st + st / 2 - cx, j * st + st / 2 - cy);
        if (far < Math.min(w, hgt) * 0.45 && (!best || dmin > best.d)) best = { d: dmin, i, j };
      }
      if (best) { const ll = m.unproject([best.i * st + st / 2, best.j * st + st / 2]); out.inscribe = { c: [+ll.lng.toFixed(4), +ll.lat.toFixed(4)], r: Math.sqrt(best.d) * st }; }
    }
    if (cmd.scan) { // Hilfsabfrage: größte Flächen einer Quellschicht im Bild (Mitte, Größe der Hülle)
      const seen = new Map();
      for (const f of m.querySourceFeatures('basemap', { sourceLayer: cmd.scan.layer, filter: cmd.scan.filter })) {
        const ring = f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] : f.geometry.coordinates?.[0]?.[0];
        if (!Array.isArray(ring) || !Array.isArray(ring[0])) continue;
        const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
        const w = Math.max(...xs) - Math.min(...xs), hh = Math.max(...ys) - Math.min(...ys);
        const key = `${(xs[0]).toFixed(4)},${(ys[0]).toFixed(4)}`;
        seen.set(key, { n: f.properties.name ?? '', k: f.properties.kind ?? '', c: [+((Math.max(...xs) + Math.min(...xs)) / 2).toFixed(4), +((Math.max(...ys) + Math.min(...ys)) / 2).toFixed(4)], a: +(w * hh * 1e4).toFixed(2) });
      }
      out.scan = [...seen.values()].sort((a, b) => b.a - a.a).slice(0, cmd.scan.top ?? 12);
    }
    if (cmd.kinds) { // Hilfsabfrage: Zählung der Arten (kind, kind_detail) einer Quellschicht im Bild
      const t = {};
      for (const f of m.querySourceFeatures('basemap', { sourceLayer: cmd.kinds })) { const k = `${f.properties.kind ?? ''}|${f.properties.kind_detail ?? ''}|${f.geometry.type}`; t[k] = (t[k] ?? 0) + 1; }
      out.kinds = t;
    }
    if (cmd.flow) { // Hilfsabfrage: Richtung und Art der Wasserlinien (erste und letzte Koordinate), um Fließrichtung gegen bekannte Flüsse zu prüfen
      const kinds = {}, named = [];
      for (const f of m.querySourceFeatures('basemap', { sourceLayer: 'water' })) {
        const g = f.geometry; if (g.type !== 'LineString' && g.type !== 'MultiLineString') { const k = `${g.type}:${f.properties.kind ?? ''}`; kinds[k] = (kinds[k] ?? 0) + 1; continue; }
        const k = `${g.type}:${f.properties.kind ?? ''}`; kinds[k] = (kinds[k] ?? 0) + 1;
        const n = f.properties.name; if (n && cmd.flow.names?.includes(n)) { const l = g.type === 'LineString' ? g.coordinates : g.coordinates[0]; named.push({ n, k: f.properties.kind, a: l[0].map((v) => +v.toFixed(4)), b: l[l.length - 1].map((v) => +v.toFixed(4)), len: l.length }); }
      }
      out.flow = { kinds, named: named.slice(0, cmd.flow.top ?? 20) };
    }
    out.ripples = ripples?.stats?.();
    document.documentElement.dataset.debugOut = JSON.stringify(out);
  });
}

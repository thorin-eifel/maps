// Infrastruktur-Zeichen (Windrad, Ladesäule, Defibrillator, Feuerwache, Krankenhaus) und ihre Karteneben-Beschreibung.
// Alles eigene Zeichnung auf Canvas, keine Vorlage, nichts wird nachgeladen. Daten: infrastruktur.json (OpenStreetMap über Overpass, wöchentlich).
// Karte um 1450: nur Windmühle (statt Windrad) und Spital (statt Krankenhaus); Ladesäule, Defibrillator und Feuerwache gab es nicht und werden dort ausgeblendet.
// Aufrufer: lage.js (initMap: registerInfra, applyInfra).
export const INFRA_KINDS = ['wind', 'charging', 'aed', 'fire_station', 'hospital', 'weir', 'lock', 'bridge', 'tunnel', 'ferry', 'picnic', 'shelter', 'bathing', 'school', 'townhall', 'cemetery'];
export const SACRAL_KINDS = ['church', 'chapel', 'cross', 'shrine', 'watermill', 'windmill', 'ford', 'border', 'gallows', 'well'];   // nur auf der Karte um 1450 gezeichnet
export const INFRA_WORD = { wind: 'Windrad', charging: 'Ladesäule', aed: 'Defibrillator (AED)', fire_station: 'Feuerwache', hospital: 'Krankenhaus', weir: 'Wehr', lock: 'Schleuse', bridge: 'Brücke', tunnel: 'Tunnel', ferry: 'Fähranleger', picnic: 'Rastplatz', shelter: 'Schutzhütte', bathing: 'Badestelle', church: 'Kirche', chapel: 'Kapelle', cross: 'Wegkreuz', shrine: 'Bildstock', school: 'Schule', townhall: 'Rathaus', cemetery: 'Friedhof' };
export const INFRA_WORD_MED = { wind: 'Windmühle', hospital: 'Spital', watermill: 'Mühle', windmill: 'Windmühle', ford: 'Furt', ferry: 'Fähre', gallows: 'Galgen', border: '', well: '' };
export const INFRA_COLOR = { wind: '#0f766e', charging: '#0369a1', aed: '#15803d', fire_station: '#8b1e3f', hospital: '#1e3a8a',
  weir: '#0e7490', lock: '#0e7490', ferry: '#0e7490', bridge: '#52525b', tunnel: '#52525b', picnic: '#a16207', shelter: '#a16207', bathing: '#0284c7', school: '#be185d', townhall: '#475569', cemetery: '#4d7c0f' };
export const INFRA_MEDIEVAL = new Set(['wind', 'hospital', 'church', 'chapel', 'cross', 'shrine', 'watermill', 'windmill', 'ford', 'border', 'gallows', 'well', 'ferry', 'bridge']);   // Arten, die es auch auf der Karte um 1450 gibt (als Windmühle und Spital)
const PX = 56;            // Plakette 28 px auf dem Schirm bei Pixelverhältnis 2
const INK = '#3a2614', PAPER = '#efe0b0', ROOF = '#a33a22', STONE = '#d9c68f';

const canvas = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d', { willReadFrequently: true }); x.lineCap = 'round'; x.lineJoin = 'round'; return x; };
const put = (map, id, data) => { if (map.hasImage(id)) map.updateImage(id, data); else map.addImage(id, data, { pixelRatio: 2 }); };

// Glyphen in einem 56er Raster, weiß auf farbigem Grund
const glyph = {
  wind(x) {
    x.strokeStyle = '#fff'; x.fillStyle = '#fff'; x.lineWidth = 3;
    x.beginPath(); x.moveTo(28, 48); x.lineTo(28, 27); x.stroke();
    for (const a of [-90, 30, 150]) { const r = (a * Math.PI) / 180; x.beginPath(); x.moveTo(28, 24); x.lineTo(28 + Math.cos(r) * 17, 24 + Math.sin(r) * 17); x.lineWidth = 3.4; x.stroke(); }
    x.beginPath(); x.arc(28, 24, 3.4, 0, Math.PI * 2); x.fill();
  },
  charging(x) {
    x.fillStyle = '#fff'; x.beginPath();
    [[31, 7], [17, 31], [26.5, 31], [24, 49], [39, 24], [29.5, 24]].forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b)));
    x.closePath(); x.fill();
  },
  aed(x, col) {
    x.fillStyle = '#fff'; x.beginPath(); x.moveTo(28, 46);
    x.bezierCurveTo(6, 30, 12, 10, 28, 21); x.bezierCurveTo(44, 10, 50, 30, 28, 46); x.fill();
    x.fillStyle = col; x.beginPath();
    [[30.5, 18], [22, 30], [27.5, 30], [25, 40], [35, 27], [29.5, 27]].forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b)));
    x.closePath(); x.fill();
  },
  fire_station(x, col) {
    x.fillStyle = '#fff'; x.beginPath(); x.moveTo(28, 7);
    x.bezierCurveTo(33, 17, 43, 22, 41, 34); x.bezierCurveTo(40, 44, 34, 49, 28, 49);
    x.bezierCurveTo(21, 49, 15, 44, 15, 35); x.bezierCurveTo(15, 29, 19, 25, 21, 19);
    x.bezierCurveTo(24, 24, 26, 23, 26, 17); x.bezierCurveTo(26, 13, 27, 10, 28, 7); x.fill();
    x.fillStyle = col; x.beginPath(); x.moveTo(28, 29); x.bezierCurveTo(33, 35, 35, 38, 33, 43); x.bezierCurveTo(32, 46, 30, 46, 28, 46);
    x.bezierCurveTo(25, 46, 22, 44, 22, 40); x.bezierCurveTo(22, 36, 26, 34, 28, 29); x.fill();
  },
  hospital(x) {
    x.fillStyle = '#fff'; x.fillRect(23.5, 11, 9, 34); x.fillRect(11, 23.5, 34, 9);
  },
  weir(x) {   // Wehr: Balken über der Strömung
    x.fillStyle = '#fff'; x.fillRect(10, 14, 36, 6);
    x.strokeStyle = '#fff'; x.lineWidth = 3; for (const y of [30, 40]) { x.beginPath(); x.moveTo(10, y); x.bezierCurveTo(18, y - 6, 24, y + 6, 32, y); x.bezierCurveTo(37, y - 4, 41, y + 3, 46, y); x.stroke(); }
  },
  lock(x) {   // Schleuse: zwei Tore und Pfeil dazwischen
    x.fillStyle = '#fff'; x.fillRect(10, 10, 7, 36); x.fillRect(39, 10, 7, 36);
    x.beginPath(); x.moveTo(21, 28); x.lineTo(30, 20); x.lineTo(30, 25); x.lineTo(35, 25); x.lineTo(35, 31); x.lineTo(30, 31); x.lineTo(30, 36); x.closePath(); x.fill();
  },
  bridge(x) {   // Brücke: Bogen unter der Fahrbahn
    x.fillStyle = '#fff'; x.fillRect(7, 20, 42, 5);
    x.strokeStyle = '#fff'; x.lineWidth = 4; x.beginPath(); x.arc(28, 46, 18, Math.PI * 1.12, Math.PI * 1.88); x.stroke();
    x.lineWidth = 2.6; for (const dx of [-8, 0, 8]) { x.beginPath(); x.moveTo(28 + dx, 25); x.lineTo(28 + dx, 31 + Math.abs(dx) * 0.2); x.stroke(); }
  },
  tunnel(x) {   // Tunnelmund
    x.fillStyle = '#fff'; x.beginPath(); x.moveTo(8, 46); x.lineTo(8, 28); x.arc(28, 28, 20, Math.PI, 0); x.lineTo(48, 46); x.closePath(); x.fill();
    x.fillStyle = INFRA_COLOR.tunnel; x.beginPath(); x.moveTo(16, 46); x.lineTo(16, 30); x.arc(28, 30, 12, Math.PI, 0); x.lineTo(40, 46); x.closePath(); x.fill();
  },
  ferry(x) {   // Boot auf Wellen
    x.fillStyle = '#fff'; x.beginPath(); x.moveTo(9, 29); x.lineTo(47, 29); x.lineTo(40, 40); x.lineTo(16, 40); x.closePath(); x.fill();
    x.fillRect(24, 16, 14, 11); x.fillRect(29, 9, 4, 8);
    x.strokeStyle = '#fff'; x.lineWidth = 2.6; x.beginPath(); x.moveTo(9, 46); x.bezierCurveTo(16, 42, 22, 50, 28, 46); x.bezierCurveTo(34, 42, 40, 50, 47, 46); x.stroke();
  },
  picnic(x) {   // Tisch mit Bänken
    x.fillStyle = '#fff'; x.fillRect(11, 20, 34, 6); x.fillRect(14, 28, 5, 18); x.fillRect(37, 28, 5, 18); x.fillRect(8, 34, 40, 4);
  },
  shelter(x) {   // Schutzhütte: Dach auf zwei Pfosten
    x.fillStyle = '#fff'; x.beginPath(); x.moveTo(6, 25); x.lineTo(28, 9); x.lineTo(50, 25); x.closePath(); x.fill();
    x.fillRect(12, 27, 5, 20); x.fillRect(39, 27, 5, 20);
  },
  bathing(x) {   // Schwimmer auf Wellen
    x.fillStyle = '#fff'; x.beginPath(); x.arc(21, 20, 5, 0, Math.PI * 2); x.fill();
    x.strokeStyle = '#fff'; x.lineWidth = 3.4; x.beginPath(); x.moveTo(25, 26); x.lineTo(40, 22); x.stroke();
    x.lineWidth = 3; for (const y of [35, 44]) { x.beginPath(); x.moveTo(9, y); x.bezierCurveTo(16, y - 6, 22, y + 6, 29, y); x.bezierCurveTo(35, y - 5, 41, y + 4, 47, y); x.stroke(); }
  },
  school(x, col) {   // Doktorhut (Barett mit Quaste)
    x.fillStyle = '#fff'; x.beginPath(); x.moveTo(28, 11); x.lineTo(50, 23); x.lineTo(28, 35); x.lineTo(6, 23); x.closePath(); x.fill();
    x.beginPath(); x.moveTo(15, 31); x.lineTo(15, 40); x.bezierCurveTo(22, 46, 34, 46, 41, 40); x.lineTo(41, 31); x.lineTo(28, 38); x.closePath(); x.fill();
    x.strokeStyle = '#fff'; x.lineWidth = 2.6; x.beginPath(); x.moveTo(46, 25); x.lineTo(46, 39); x.stroke();
  },
  townhall(x, col) {   // Giebelhaus mit Säulen
    x.fillStyle = '#fff'; x.beginPath(); x.moveTo(28, 8); x.lineTo(50, 21); x.lineTo(6, 21); x.closePath(); x.fill();
    for (const a of [10, 20, 30, 40]) x.fillRect(a, 24, 6, 17);
    x.fillRect(7, 43, 42, 5);
  },
  cemetery(x, col) {   // lateinisches Kreuz auf Sockel
    x.fillStyle = '#fff'; x.fillRect(25, 8, 6, 36); x.fillRect(15, 18, 26, 6); x.fillRect(14, 44, 28, 4);
  },
};

function plaque(kind) {
  const x = canvas(PX, PX), col = INFRA_COLOR[kind];
  x.beginPath(); x.arc(28, 28, 26, 0, Math.PI * 2); x.fillStyle = '#fff'; x.fill();
  x.beginPath(); x.arc(28, 28, 23, 0, Math.PI * 2); x.fillStyle = col; x.fill();
  glyph[kind](x, col);
  return x.getImageData(0, 0, PX, PX);
}

// Zeichen der Karte um 1450: Tinte, Pergamentfüllung, zinnoberrote Dächer, heller Saum (wie die Siedlungszeichen)
const S = 44;
function medDraw(kind) {
  const x = canvas(S, S);
  const P = (pts, fill, w = 1.4) => {
    x.beginPath(); pts.forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b))); x.closePath();
    x.lineWidth = 5; x.strokeStyle = PAPER; x.stroke(); x.fillStyle = fill; x.fill(); x.lineWidth = w; x.strokeStyle = INK; x.stroke();
  };
  if (kind === 'wind' || kind === 'windmill') {
    P([[14, 41], [18, 19], [26, 19], [30, 41]], PAPER); P([[16, 19], [22, 10], [28, 19]], ROOF);
    P([[20, 41], [20, 34], [24, 34], [24, 41]], INK);
    for (const [a, b] of [[22, 15, 7, 2], [22, 15, 37, 28], [22, 15, 37, 2], [22, 15, 7, 28]].map(([cx, cy, ex, ey]) => [[cx, cy], [ex, ey]])) {
      x.beginPath(); x.moveTo(a[0], a[1]); x.lineTo(b[0], b[1]); x.lineWidth = 4.4; x.strokeStyle = PAPER; x.stroke(); x.lineWidth = 1.8; x.strokeStyle = INK; x.stroke();
    }
  } else if (kind === 'watermill') {   // Mühlhaus mit Wasserrad
    P([[6, 40], [6, 20], [26, 20], [26, 40]], PAPER); P([[3, 20], [16, 9], [29, 20]], ROOF);
    x.beginPath(); x.arc(33, 30, 9, 0, Math.PI * 2); x.lineWidth = 4.4; x.strokeStyle = PAPER; x.stroke(); x.lineWidth = 1.8; x.strokeStyle = INK; x.stroke();
    x.lineWidth = 1.4; for (let a = 0; a < 6; a++) { const t = (a * Math.PI) / 3; x.beginPath(); x.moveTo(33, 30); x.lineTo(33 + Math.cos(t) * 9, 30 + Math.sin(t) * 9); x.stroke(); }
    P([[13, 40], [13, 31], [18, 31], [18, 40]], INK);
  } else if (kind === 'ford') {   // Furt: zwei Wellenlinien und Trittsteine
    x.lineWidth = 5; x.strokeStyle = PAPER; x.beginPath(); x.moveTo(5, 18); x.bezierCurveTo(13, 12, 19, 24, 27, 18); x.bezierCurveTo(33, 13, 37, 21, 40, 18); x.moveTo(5, 30); x.bezierCurveTo(13, 24, 19, 36, 27, 30); x.bezierCurveTo(33, 25, 37, 33, 40, 30); x.stroke();
    x.lineWidth = 1.6; x.strokeStyle = INK; x.stroke();
    x.fillStyle = INK; for (const [a, b] of [[12, 24], [20, 24], [28, 24], [36, 24]]) { x.beginPath(); x.arc(a, b, 2.4, 0, Math.PI * 2); x.fill(); }
  } else if (kind === 'ferry') {   // Fähre: Kahn mit Mast
    P([[6, 28], [38, 28], [32, 38], [12, 38]], PAPER); x.strokeStyle = INK; x.lineWidth = 1.8; x.beginPath(); x.moveTo(22, 28); x.lineTo(22, 7); x.stroke();
    P([[22, 8], [34, 24], [22, 24]], PAPER);
    x.lineWidth = 1.4; x.beginPath(); x.moveTo(5, 42); x.bezierCurveTo(12, 38, 17, 45, 23, 42); x.bezierCurveTo(29, 38, 34, 45, 40, 42); x.stroke();
  } else if (kind === 'border') {   // Grenzstein: kleiner Pfeiler mit Kreuzzeichen
    P([[14, 41], [15, 18], [22, 12], [29, 18], [30, 41]], STONE);
    x.strokeStyle = INK; x.lineWidth = 1.6; x.beginPath(); x.moveTo(22, 20); x.lineTo(22, 31); x.moveTo(17.5, 25); x.lineTo(26.5, 25); x.stroke();
  } else if (kind === 'gallows') {   // Galgen: Pfosten, Balken, Strebe
    x.lineCap = 'butt'; x.strokeStyle = PAPER; x.lineWidth = 6; x.beginPath(); x.moveTo(12, 41); x.lineTo(12, 7); x.lineTo(34, 7); x.moveTo(12, 17); x.lineTo(21, 7); x.stroke();
    x.strokeStyle = INK; x.lineWidth = 3; x.stroke(); x.lineWidth = 1.2; x.beginPath(); x.moveTo(30, 7); x.lineTo(30, 16); x.stroke();
  } else if (kind === 'well') {   // Brunnen: Rand mit Dach und Eimer
    P([[9, 41], [9, 29], [35, 29], [35, 41]], STONE); P([[7, 14], [22, 6], [37, 14]], ROOF);
    x.strokeStyle = INK; x.lineWidth = 2.2; x.beginPath(); x.moveTo(11, 14); x.lineTo(11, 29); x.moveTo(33, 14); x.lineTo(33, 29); x.stroke();
    x.lineWidth = 1.2; x.beginPath(); x.moveTo(22, 14); x.lineTo(22, 23); x.stroke(); P([[19, 23], [25, 23], [24, 28], [20, 28]], PAPER, 1.2);
  } else if (kind === 'bridge') {   // alte Brücke: gemauerter Bogen
    P([[3, 22], [41, 22], [41, 28], [3, 28]], STONE);
    P([[7, 28], [37, 28], [37, 40], [30, 40], [30, 36], [22, 30], [14, 36], [14, 40], [7, 40]], STONE);
    x.strokeStyle = INK; x.lineWidth = 1.4; x.beginPath(); x.moveTo(14, 40); x.quadraticCurveTo(22, 26, 30, 40); x.stroke();
  } else if (kind === 'church') {   // Langhaus mit Turm und Kreuz
    P([[6, 40], [6, 24], [26, 24], [26, 40]], PAPER); P([[3, 24], [16, 14], [29, 24]], ROOF);
    P([[26, 40], [26, 14], [36, 14], [36, 40]], PAPER); P([[25, 14], [31, 3], [37, 14]], ROOF);
    x.strokeStyle = INK; x.lineWidth = 1.6; x.beginPath(); x.moveTo(31, 3); x.lineTo(31, -1); x.moveTo(29, 1); x.lineTo(33, 1); x.stroke();
    P([[14, 40], [14, 32], [18, 32], [18, 40]], INK);
  } else if (kind === 'chapel') {   // Kapelle: kleines Haus mit Dachreiter
    P([[10, 40], [10, 22], [32, 22], [32, 40]], PAPER); P([[7, 22], [21, 11], [35, 22]], ROOF);
    P([[18, 40], [18, 31], [24, 31], [24, 40]], INK);
    x.strokeStyle = INK; x.lineWidth = 1.6; x.beginPath(); x.moveTo(21, 11); x.lineTo(21, 4); x.moveTo(18.5, 6.5); x.lineTo(23.5, 6.5); x.stroke();
  } else if (kind === 'cross') {   // Wegkreuz auf Steinsockel
    P([[14, 41], [16, 33], [28, 33], [30, 41]], STONE);
    x.lineCap = 'butt'; x.strokeStyle = PAPER; x.lineWidth = 7; x.beginPath(); x.moveTo(22, 33); x.lineTo(22, 6); x.moveTo(14, 15); x.lineTo(30, 15); x.stroke();
    x.strokeStyle = INK; x.lineWidth = 3; x.beginPath(); x.moveTo(22, 33); x.lineTo(22, 6); x.moveTo(14, 15); x.lineTo(30, 15); x.stroke();
  } else if (kind === 'shrine') {   // Bildstock: Pfeiler mit Nische und Dach
    P([[16, 41], [16, 17], [28, 17], [28, 41]], STONE); P([[13, 17], [22, 8], [31, 17]], ROOF);
    P([[19.5, 32], [19.5, 22], [24.5, 22], [24.5, 32]], INK);
  } else {   // hospital: Haus mit Kreuz
    P([[8, 41], [8, 21], [36, 21], [36, 41]], PAPER); P([[5, 21], [22, 9], [39, 21]], ROOF);
    x.fillStyle = ROOF; x.fillRect(19.5, 25, 5, 13); x.fillRect(16, 28.5, 12, 5);
    x.strokeStyle = INK; x.lineWidth = 1; x.strokeRect(19.5, 25, 5, 13); x.strokeRect(16, 28.5, 12, 5);
  }
  return x.getImageData(0, 0, S, S);
}

export function registerInfra(map) {
  for (const k of INFRA_KINDS) put(map, `inf-${k}`, plaque(k));
  for (const k of INFRA_MEDIEVAL) put(map, `med-inf-${k}`, medDraw(k));
}

// Eigenschaften je Objekt für die Karte: Beschriftung nur bei Wache, Krankenhaus und benanntem Windrad
export function infraFeatures(items) {
  return { type: 'FeatureCollection', features: (items ?? []).map((i) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [i.lon, i.lat] },
    properties: { kind: i.kind, old: i.old ?? 0, name: i.name || '', label: i.name || (['wind', 'fire_station', 'hospital'].includes(i.kind) ? INFRA_WORD[i.kind] : ''), labelMed: ['cross', 'shrine', 'border', 'well'].includes(i.kind) ? '' : ['watermill', 'windmill', 'ford', 'gallows'].includes(i.kind) ? INFRA_WORD_MED[i.kind] : i.kind === 'wind' ? (i.name || INFRA_WORD_MED.wind) : ['church', 'chapel', 'bridge', 'ferry'].includes(i.kind) ? (i.name || (i.kind === 'ferry' ? INFRA_WORD_MED.ferry : '')) : (i.name || INFRA_WORD_MED[i.kind] || ''), kw: i.kw ?? null, points: i.points ?? null } })) };
}

// Text für das Popup: Art, Sachwert, Herkunft. Reiner Text, kein HTML.
export function infraText(p) {
  const bits = [INFRA_WORD[p.kind] ?? p.kind];
  if (p.name && !['aed', 'cross', 'shrine', 'picnic', 'shelter'].includes(p.kind)) bits.push(p.name);
  if (p.kind === 'wind' && p.kw) bits.push(p.kw >= 1000 ? `${(p.kw / 1000).toLocaleString('de-DE', { maximumFractionDigits: 1 })} MW` : `${p.kw} kW`);
  if (p.kind === 'charging' && p.points) bits.push(`${p.points} Ladepunkt${p.points === 1 ? '' : 'e'}`);
  return bits.join(' · ');
}

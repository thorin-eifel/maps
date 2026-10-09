// Ansichten für DWD-Indizes (Waldbrand, Pollen, UV), Spritpreise und Themenradar.
// Reine Darstellung: bekommt die geladenen JSON-Objekte und die Hilfsfunktionen aus lage.js. Kein eigener Abruf, keine Speicherung.
const WBI = { 1: 'sehr gering', 2: 'gering', 3: 'mittel', 4: 'hoch', 5: 'sehr hoch' };
const WBI_SEV = { 3: 'notice', 4: 'warning', 5: 'critical' };
const UV_TEXT = (v) => (v == null ? '–' : v <= 2 ? 'niedrig' : v <= 5 ? 'mittel' : v <= 7 ? 'hoch' : v <= 10 ? 'sehr hoch' : 'extrem');
const DAY = ['heute', 'morgen', 'übermorgen'];
const POLLEN_NAME = { Hasel: 'Hasel', Erle: 'Erle', Esche: 'Esche', Birke: 'Birke', Graeser: 'Gräser', Roggen: 'Roggen', Beifuss: 'Beifuß', Ambrosia: 'Ambrosia' };

function section(h, title, note) {
  return h('div', { class: 'card-f' }, h('strong', {}, title), note ? h('span', { class: 'muted small' }, note) : null);
}

function level(h, sevBadge, n) {
  if (!Number.isFinite(n)) return h('span', { class: 'muted' }, '–');
  return h('span', { class: `lvl${WBI_SEV[n] ? ` sev-${WBI_SEV[n]}` : ''}` }, `${n} ${WBI[n] ?? ''}`);
}

export function renderIndizes(panel, idx, { h, sevBadge, sourceLine, ageEl }) {
  if (!idx) return;
  const fire = idx.fire?.stations ?? [];
  panel.append(section(h, 'Waldbrand- und Graslandfeuerindex', 'Stufe 1 bis 5, Stationswerte des DWD'));
  if (!fire.length) {
    panel.append(h('div', { class: 'empty' }, 'Noch keine Werte.'));
  } else {
    const head = h('tr', {}, h('th', { scope: 'col' }, 'Station'), ...DAY.slice(0, 2).map((d) => h('th', { scope: 'col' }, `Wald ${d}`)), h('th', { scope: 'col' }, 'Gras heute'));
    panel.append(h('div', { class: 'scroll-x' }, h('table', { class: 'wx-others' },
      h('caption', { class: 'sr-only' }, 'Waldbrand- und Graslandfeuerindex je Station'), h('thead', {}, head),
      h('tbody', {}, ...fire.map((s) => h('tr', {},
        h('th', { scope: 'row' }, s.name, h('span', { class: 'muted small' }, ` · ${Math.round(s.distance_km)} km`)),
        h('td', {}, level(h, sevBadge, s.wbi[0])), h('td', {}, level(h, sevBadge, s.wbi[1])),
        h('td', {}, level(h, sevBadge, s.glfi?.[0]))))))));
    panel.append(h('div', { class: 'card-f' }, h('span', { class: 'muted small' }, `Ausgabe ${fire[0].issued}. Kein amtliches Warnsystem: Waldbrandwarnungen kommen von den Ländern.`)));
  }
  if (idx.fire?.source) panel.append(sourceLine(idx.fire.source));

  const regions = idx.pollen?.regions ?? [];
  panel.append(section(h, 'Pollenflug', 'Gefahrenindex 0 bis 3 je Teilregion'));
  if (!regions.length) {
    panel.append(h('div', { class: 'empty' }, 'Noch keine Werte.'));
  } else {
    for (const r of regions) {
      const today = r.days?.today ?? {}, tomorrow = r.days?.tomorrow ?? {};
      const kinds = Object.keys(today);
      const relevant = kinds.filter((k) => today[k] !== '0' || tomorrow[k] !== '0');
      panel.append(h('div', { class: 'pegel' },
        h('h3', {}, r.name),
        h('div', { class: 'val' }, relevant.length ? `${relevant.length} aktiv` : 'keine Belastung'),
        h('div', { class: 'muted' }, relevant.length
          ? relevant.map((k) => `${POLLEN_NAME[k] ?? k} ${today[k]} (morgen ${tomorrow[k]})`).join(' · ')
          : 'Heute und morgen keine nennenswerte Belastung'),
        h('div', { class: 'muted right' }, idx.pollen.last_update ?? '')));
    }
  }
  if (idx.pollen?.source) panel.append(sourceLine(idx.pollen.source));

  const uv = idx.uv;
  if (uv?.station) {
    panel.append(section(h, 'UV-Index', `Station ${uv.station} (Hunsrück), höchster zu erwartender Wert des Tages`));
    panel.append(h('div', { class: 'pegel' },
      h('h3', {}, 'UV-Gefahrenindex'), h('div', { class: 'val' }, `${uv.today ?? '–'} ${UV_TEXT(uv.today)}`),
      h('div', { class: 'muted' }, `morgen ${uv.tomorrow ?? '–'} (${UV_TEXT(uv.tomorrow)}) · übermorgen ${uv.dayafter ?? '–'} (${UV_TEXT(uv.dayafter)})`),
      h('div', { class: 'muted right' }, uv.last_update ?? '')));
    if (uv.source) panel.append(sourceLine(uv.source));
  }
}

const EUR = (v) => Number(v).toFixed(3).replace('.', ',');   // Einheit steht in der Kopfzeile

export function renderFuel(panel, fuel, { h, sourceLine, ageEl }) {
  panel.replaceChildren();
  panel.append(h('div', { class: 'card-f' }, h('strong', {}, 'Spritpreise, deutsche Seite der Grenze')));
  if (!fuel || fuel.source?.status === 'disabled' || !fuel.stations?.length) {
    panel.append(h('div', { class: 'empty' }, fuel?.source?.status === 'disabled'
      ? 'Quelle ist abgeschaltet: Es fehlt der kostenlose Tankerkönig-Schlüssel auf dem Sammelrechner.'
      : 'Noch keine Preise.'));
    if (fuel?.source) panel.append(sourceLine(fuel.source));
  } else {
    const stats = Object.values(fuel.stats);
    panel.append(h('div', { class: 'scroll-x' }, h('table', { class: 'wx-others nums' },
      h('caption', {}, `Spanne in ${fuel.stations.length} Stationen im Umkreis`),
      h('thead', {}, h('tr', {}, ...['€/l', 'Min', 'Median', 'Max'].map((t) => h('th', { scope: 'col' }, t)))),
      h('tbody', {}, ...stats.map((s) => h('tr', {}, h('th', { scope: 'row' }, s.label), h('td', {}, EUR(s.min)), h('td', {}, EUR(s.median)), h('td', {}, EUR(s.max))))))));
    const rows = fuel.stations.slice(0, 12);
    panel.append(h('div', { class: 'scroll-x' }, h('table', { class: 'wx-others nums' },
      h('caption', {}, 'Günstigste Stationen nach Diesel'),
      h('thead', {}, h('tr', {}, ...['Tankstelle', 'E10 €', 'Diesel €'].map((t) => h('th', { scope: 'col' }, t)))),
      h('tbody', {}, ...rows.map((r) => h('tr', {},
        h('th', { scope: 'row' }, h('span', { class: 'st-name' }, r.name),
          h('span', { class: 'muted small st-sub' }, `${r.ort ?? ''} · ${Math.round(r.distance_km)} km · `, ageEl(r.prices.diesel?.ts ?? r.prices.e10?.ts))),
        h('td', {}, r.prices.e10 ? EUR(r.prices.e10.value) : '–'), h('td', {}, r.prices.diesel ? EUR(r.prices.diesel.value) : '–')))))));
    panel.append(sourceLine(fuel.source));
  }
  const lu = fuel?.lu, mx = lu?.max_prices ?? {};
  panel.append(h('div', { class: 'card-f' }, h('strong', {}, 'Luxemburg: amtliche Höchstpreise')));
  if (!mx.sp95 && !mx.sp98 && !mx.diesel) {
    panel.append(h('div', { class: 'empty' }, 'Noch keine Höchstpreise.'));
  } else {
    const day = (d) => String(d ?? '').split('-').reverse().join('.');
    panel.append(h('div', { class: 'scroll-x' }, h('table', { class: 'wx-others nums' },
      h('caption', {}, 'Höchstpreis, nicht Stationspreis'),
      h('thead', {}, h('tr', {}, ...['€/l', 'Höchstens', 'gilt ab'].map((t) => h('th', { scope: 'col' }, t)))),
      h('tbody', {}, ...[['sp95', 'Super 95'], ['sp98', 'Super 98'], ['diesel', 'Diesel']].filter(([k]) => mx[k]).map(([k, label]) =>
        h('tr', {}, h('th', { scope: 'row' }, label), h('td', {}, EUR(mx[k].value)), h('td', {}, day(mx[k].valid_from))))))));
  }
  if (lu?.max_source) panel.append(sourceLine(lu.max_source));
  panel.append(h('div', { class: 'card-f' }, h('span', { class: 'muted small' },
    `Der Staat setzt diese Höchstpreise für ganz Luxemburg fest. Einzelne Tankstellen dürfen darunter liegen; offene Preise je Station gibt es dort nicht. Die ${lu?.stations?.length ?? 0} Standorte auf der Karte stammen aus OpenStreetMap und zeigen deshalb nur diesen Höchstpreis (mit „≤“).`)));
}

export function renderThemen(panel, themen, { h, sourceLine }) {
  panel.replaceChildren();
  panel.append(h('div', { class: 'card-f' }, h('strong', {}, 'Themenradar'), h('span', { class: 'muted small' }, 'nur Zählungen öffentlicher Mastodon-Beiträge')));
  const r = themen?.radar;
  if (!r) {
    panel.append(h('div', { class: 'empty' }, 'Noch keine Zählung.'));
  } else {
    panel.append(h('div', { class: 'scroll-x' }, h('table', { class: 'wx-others nums' },
      h('caption', {}, `Beiträge mit Regions-Hashtag, letzte ${r.window_h} Stunden`),
      h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Hashtag'), h('th', { scope: 'col' }, 'Beiträge'))),
      h('tbody', {}, ...r.regions.map((x) => h('tr', {}, h('th', { scope: 'row' }, `#${x.tag}`), h('td', {}, x.posts)))))));
    panel.append(r.topics.length
      ? h('div', { class: 'scroll-x' }, h('table', { class: 'wx-others nums' },
        h('caption', {}, `Begleitende Themen (ab ${r.k_min} verschiedenen Konten)`),
        h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Thema'), h('th', { scope: 'col' }, 'Beiträge'))),
        h('tbody', {}, ...r.topics.map((x) => h('tr', {}, h('th', { scope: 'row' }, `#${x.tag}`), h('td', {}, x.posts))))))
      : h('div', { class: 'empty' }, `Kein begleitendes Thema erreicht die Schwelle von ${r.k_min} verschiedenen Konten.`));
    panel.append(h('div', { class: 'card-f' }, h('span', { class: 'muted small' },
      `${r.posts_total} Beiträge gezählt auf ${r.instance}. Keine Texte, Namen oder Konten gespeichert. Mastodon ist klein und deutschlandweit gestreut: Das ist ein Themenzähler, keine Stimmung der Region.`)));
  }
  if (themen?.source) panel.append(sourceLine(themen.source));
}

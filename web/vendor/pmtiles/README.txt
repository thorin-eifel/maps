pmtiles 4.5.0 (BSD-3-Clause), aus dem npm-Paket "pmtiles", zusammen mit fflate 0.8.3 (MIT) mit esbuild zu einer Datei
gebündelt (Einstieg: export { PMTiles, Protocol, FetchSource } from 'pmtiles'; minify). Keine Codeänderung.
Update: npm i pmtiles esbuild; npx esbuild entry.js --bundle --format=esm --minify --legal-comments=none --outfile=pmtiles.js

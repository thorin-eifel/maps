# Datenschutzfolgeabschätzung — Entwurf (Phase 1)

Status: Entwurf, dünn wie angekündigt. Rechtliche Endabnahme vor öffentlichem Start durch Berater oder Datenschutzbeauftragte.

## Verarbeitung
Abruf offener Daten (Warnungen, Verkehr, Pegel, Wetter), Speicherung als Ereignisse und Messwerte, Anzeige in einer Web-App.

## Personenbezug
| Quelle | Personenbezug möglich? | Maßnahme |
|---|---|---|
| NINA (BBK) | Freitext behördlicher Warnungen; enthält gelegentlich Behörden-Kontaktdaten, keine Privatpersonen | Text auf 700 Zeichen gekürzt, HTML entfernt |
| DWD WFS, Bright Sky | nein | — |
| PEGELONLINE | nein | — |
| Autobahn-API | Verkehrsmeldungen ohne Personen; keine Kamerabilder eingebunden | Kameras bewusst ausgeschlossen |

Social-Media-Quellen, Telegram, Kamerabilder, Fotos: **nicht Teil von Phase 1**.

## Besucher und Hosting
Keine Cookies, keine Drittanbieter, keine externen Schriften/Kacheln. Die Seite ist statisch und liegt bei IONOS (Webspace). Zugriffsprotokolle entstehen beim Hoster und liegen nicht in unserer Hand.
Offen vor dem Start: Vertrag zur Auftragsverarbeitung mit IONOS abschließen, Speicherdauer und IP-Kürzung der Logs beim Hoster prüfen, Angaben in „Datenschutz“ ergänzen.

## Sammelstelle
Ein Rechner von CTW ruft die Quellen ab und lädt ausschließlich fertige JSON-Dateien (Ereignisse, Messwerte, Quellenstatus) per SFTP hoch. Kontaktadresse im User-Agent gegenüber den Quellen ist eine Funktionsadresse, keine Personenadresse.

## Risiken und Restrisiko
Gering. Offen: Prüfung der Freitexte aus NINA im Echtbetrieb (Stichprobe), Lizenz- und Nutzungsbedingungen je Quelle.

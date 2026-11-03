Catálogo de traducción (G6 · E4, GD-I18N-001, issue #68). Idioma fuente: **inglés** (los textos del código).

- `geoduck_es.ts`: español, en el formato de Qt Linguist (editable con Linguist o a mano). GeoDuck lo lee tal
  cual con la biblioteca estándar de Python; no usa `.qm` ni `QTranslator` (F-106, F-107 en
  `docs/g6/acceptance.md`).

Tras cambiar textos del código: `python tools/i18n.py --write` (añade los nuevos al `.ts` sin traducir y quita
los que ya no están). La CI ejecuta `python tools/i18n.py --check`.

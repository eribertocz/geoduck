Catálogos de traducción Qt (G6 · E4, GD-I18N-001, issue #68). Idioma fuente: **inglés** (los textos del código).

- `geoduck_es.ts`: español, editable con Qt Linguist o a mano.
- `geoduck_es.qm`: compilado con `lrelease`; es el que carga GeoDuck con QGIS en español.

Tras cambiar textos del código: `python tools/i18n.py --write` (añade los nuevos al `.ts` sin traducir) y, una
vez traducidos, otra vez `--write` para recompilar el `.qm`. La CI ejecuta `python tools/i18n.py --check`.

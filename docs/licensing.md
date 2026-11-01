# Licencia de GeoDuck y de sus dependencias

**Decisión del propietario (2026-11-01):** `GPL-2.0-or-later`. Este documento registra la verificación
de sus implicaciones. No es asesoramiento legal.

## 1. Requisito del ecosistema QGIS

- El repositorio oficial de complementos exige que la licencia sea «compatible con la GPLv2 o
  posterior», que existan `README` y `LICENSE`, que el código fuente sea público y que el paquete
  **no incluya binarios** y no supere **20 MB**
  ([plugins.qgis.org/publish](https://plugins.qgis.org/publish/)).
- QGIS se licencia «GPL version 2 or greater» y espera que los complementos sigan esa licencia y
  publiquen su código fuente ([QGIS blog, 2016](https://blog.qgis.org/2016/05/29/licensing-requirements-for-qgis-)).

`GPL-2.0-or-later` cumple ambos requisitos.

## 2. Licencias de las dependencias (verificadas en metadatos de los paquetes instalados)

| Componente | Cómo lo usa GeoDuck | Licencia verificada | Compatibilidad con GPL-2.0-or-later |
|---|---|---|---|
| QGIS / PyQGIS | Host; GeoDuck lo importa | GPL-2.0-or-later (proyecto QGIS) | Misma familia |
| PyQt5 / PyQt6 | A través de `qgis.PyQt` | GPL v3 (metadato `PyQt5 5.15.11`: «GPL v3») | Compatible **solo** porque GeoDuck es «or later»: la obra combinada puede distribuirse bajo GPLv3 |
| QScintilla (vía `QgsCodeEditorSQL`) | Editor SQL (fases posteriores) | GPL v3 | Igual que PyQt |
| `duckdb` (Python) | Dependencia de ejecución | MIT (clasificador `License :: OSI Approved :: MIT License`) | Compatible |
| `pyarrow` | Dependencia de ejecución | Apache-2.0 (`License-Expression: Apache-2.0`) | Compatible con GPLv3, **no** con GPLv2-only; de nuevo requiere «or later» |
| NumPy (lo trae QGIS) | Indirecta | BSD-3-Clause | Compatible |
| Extensión DuckDB `spatial` | La instala el usuario desde DuckDB | MIT; enlaza GEOS (LGPL-2.1), PROJ (MIT), GDAL (MIT) | GeoDuck no la redistribuye |

## 3. Implicaciones

1. **Usar `GPL-2.0-or-later`, nunca `GPL-2.0-only`.** Con «only», la combinación con PyArrow
   (Apache-2.0) y con PyQt (GPLv3) no sería redistribuible.
2. **Cabecera SPDX** en cada archivo fuente: `# SPDX-License-Identifier: GPL-2.0-or-later`.
3. **No redistribuir binarios** de DuckDB, PyArrow ni extensiones dentro del ZIP del complemento
   (regla del repositorio oficial y límite de 20 MB). Si en el futuro el propietario aprueba otro canal
   de distribución que sí incluya wheels, se deberán incluir los avisos de licencia de cada wheel
   (en particular el `NOTICE` de Apache Arrow) y los de las bibliotecas que esos wheels empaquetan.
4. **Metadatos del complemento:** `metadata.txt` debe enlazar repositorio, issue tracker y página, y
   declarar las dependencias externas en el campo `about`.
5. Las contribuciones externas se aceptan bajo la misma licencia (inbound = outbound).

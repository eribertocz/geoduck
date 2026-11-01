# Propuesta C4 — contrato de CRS y orden de ejes

**Estado:** Propuesta para el arquitecto (2026-11-01). **No modifica** `spec/`: el texto propuesto se
incorpora solo si se aprueba.
**Afecta a:** `spec/specs/spatial-spec.md` §4 (y §5 y §8 en lo indicado).
**Depende de:** ADR-0008 (transporte GeoArrow, propuesto) para §5.
**Fase de implementación:** G3/G4. Ningún código de G0 cambia por esta propuesta.

## 1. Qué dice hoy el contrato

`spatial-spec` §4, último párrafo:

> `ST_SetCRS` etiqueta un CRS; **no transforma** coordenadas. Una reproyección real requiere
> `ST_Transform` u operación equivalente y decisión explícita. Verificar orden de ejes, particularmente
> `geometry_always_xy` de DuckDB 2.0, y contrastarlo con QGIS. Nunca realizar una transformación oculta.

El texto pide verificar, pero no fija qué hace GeoDuck con el orden de ejes. Además atribuye
`geometry_always_xy` a «DuckDB 2.0», sin precisar que pertenece a la extensión `spatial`.

## 2. Hechos verificados

| ID | Hecho | Dónde se verificó | Evidencia |
|---|---|---|---|
| F-10 | El tipo `GEOMETRY('…')` y el CRS `OGC:CRS84` existen sin `spatial`. Al leer una relación con `to_arrow_reader()`, la geometría sale como `geoarrow.wkb` con el CRS en PROJJSON; `ST_AsWKB` produce `binary` **sin** CRS | Linux, DuckDB 1.5.0–2.0.0 | `docs/evidence/g0/scripts/geo_*.py` |
| F-05 | Sin `spatial`, los CRS `EPSG:*` no se reconocen en el tipo `GEOMETRY('EPSG:…')` | Linux, DuckDB 1.5.x y 2.0.0 | `geo_core.py` |
| F-14a | `geometry_always_xy` es un ajuste de `spatial`, de tipo BOOLEAN y **sin valor por defecto** en DuckDB 2.0.0 (`duckdb_settings()` → `None`). `current_setting()` no puede leerlo mientras no se fije | Windows, QGIS 3.34.15, DuckDB 2.0.0 | `docs/evidence/g0/windows/win11-qgis-3.34.15/` §4 |
| F-14b | Con el ajuste sin fijar, `ST_Transform` **falla** y pide declarar el orden de ejes. DuckDB anuncia que en 2.1 el valor por defecto será `true` | Windows, DuckDB 2.0.0 | idem |
| F-14c | `ST_Transform(ST_Point(-68.15,-16.5),'EPSG:4326','EPSG:32719', true)` y `ST_Transform(ST_Point(-16.5,-68.15), …, false)` dan el mismo punto, `590716.04 8175564.99` (La Paz en UTM 19S) | Windows, DuckDB 2.0.0 | idem |
| F-14d | En el WKB que entrega GeoDuck, QGIS toma la coordenada **x como longitud (este)**, aunque el CRS sea `EPSG:4326` (`hasAxisInverted() = True`). Un punto con x = −68,15 e y = −16,5 transformado por QGIS a EPSG:32719 da `590716.04 8175564.99`, igual que DuckDB. Lo mismo ocurre con `OGC:CRS84` | Linux, QGIS 3.44.14 y 4.2.3, DuckDB 2.0.0 | `docs/evidence/g0/c4/` |

Conclusión de los hechos: el WKB que produce DuckDB y el que consume QGIS usan el mismo convenio
(x = este/longitud, y = norte/latitud), **siempre que la geometría se haya construido en ese orden**. El
riesgo aparece solo si el SQL del usuario produce geometrías en el orden de la autoridad, por ejemplo con
`ST_Transform(…, false)` hacia EPSG:4326.

## 3. Propuesta de decisión

1. **Sin reordenar.** El puente entrega las coordenadas del WKB tal como vienen de DuckDB (x, y). GeoDuck
   nunca intercambia ejes por su cuenta.
2. **Sin ajustes implícitos.** GeoDuck no fija `geometry_always_xy` ni otro ajuste de `spatial` en la
   sesión del usuario. El orden de ejes de `ST_Transform` es una decisión del SQL del usuario, como exige
   DuckDB 2.0.
3. **Transparencia.** Cuando `spatial` está cargada, GeoDuck informa el valor efectivo de
   `geometry_always_xy` (`true`, `false` o «sin fijar»), leído con `duckdb_settings()`. Se muestra en el
   diagnóstico y, en G4, junto al selector de geometría y CRS.
4. **CRS desde GeoArrow.** El CRS de la capa se obtiene de los metadatos GeoArrow (PROJJSON →
   `QgsCoordinateReferenceSystem.createFromUserInput`), según ADR-0008. Sin CRS declarado, rige el orden de
   preferencia actual de §4. Nunca se asume EPSG:4326.
5. **Sin transformación oculta** (se mantiene). GeoDuck no llama a `ST_Transform` salvo por una acción
   explícita y confirmada del usuario. Si esa acción existe en G4, debe declarar el orden de ejes en la
   llamada (parámetro `always_xy`), no mediante el ajuste de sesión.
6. **Sin heurísticas.** GeoDuck no intenta adivinar si unas coordenadas están invertidas a partir de sus
   rangos. Ese riesgo se documenta para el usuario.

## 4. Texto propuesto para `spatial-spec` §4 (sustituye el último párrafo)

> `ST_SetCRS` etiqueta un CRS; **no transforma** coordenadas. Una reproyección real requiere
> `ST_Transform` u operación equivalente y una decisión explícita del usuario. Nunca realizar una
> transformación oculta.
>
> **Orden de ejes.** GeoDuck entrega a QGIS las coordenadas del WKB tal como las produce DuckDB, sin
> reordenarlas; QGIS interpreta x como este/longitud también en CRS geográficos como EPSG:4326. GeoDuck no
> fija el ajuste `geometry_always_xy` de la extensión `spatial` (en DuckDB 2.0 no tiene valor por defecto y
> `ST_Transform` exige declararlo; en 2.1 pasará a `true`). Cuando `spatial` está cargada, GeoDuck muestra
> su valor efectivo. Toda transformación iniciada por GeoDuck declara el orden de ejes en la propia
> llamada. Geometrías producidas en el orden de la autoridad (por ejemplo, latitud-longitud) se entregan
> tal cual y es responsabilidad del SQL del usuario.

## 5. Cambios asociados

- §5: según ADR-0008, el transporte usa la exportación GeoArrow nativa; `ST_AsWKB` queda como alternativa
  que pierde el CRS.
- §8, añadir a las pruebas obligatorias:
  - **AX-1:** punto lon/lat en `EPSG:4326` y en `OGC:CRS84` → capa QGIS → transformación a UTM igual a la
    de DuckDB (ya automatizable con `docs/evidence/g0/c4/qgis_axis.py`).
  - **AX-2:** `geometry_always_xy` en sus tres estados (`true`, `false`, sin fijar) → valor mostrado
    correcto; GeoDuck no lo modifica.
  - **AX-3:** `ST_Transform` sin orden declarado en DuckDB 2.0 → error de DuckDB presentado como error SQL
    del usuario, sin reintentos ni ajustes automáticos.
  - **AX-4:** CRS EPSG con `spatial` → CRS reconocido en QGIS vía GeoArrow.

## 6. Consecuencias

- Pro: comportamiento predecible e idéntico en DuckDB 1.5, 2.0 y 2.1; GeoDuck no altera la sesión del
  usuario.
- Pro: con DuckDB 2.1 no hará falta ningún cambio: el valor por defecto cambia en DuckDB, no en GeoDuck.
- Contra: si el SQL del usuario genera coordenadas en orden latitud-longitud, la capa aparecerá desplazada
  en QGIS. GeoDuck lo explica en la documentación, pero no lo corrige ni lo detecta.
- Dependencia: el punto 3 necesita el diagnóstico de `spatial` (existente) y, en G4, la UI de selección
  espacial.

## 7. Preguntas para el arquitecto

1. ¿Se aprueba que GeoDuck **no** fije `geometry_always_xy`, ni siquiera a `true` para anticipar DuckDB 2.1?
2. ¿El valor efectivo debe mostrarse solo en el diagnóstico (G0/G4) o también en cada resultado espacial?

# Propuesta C4 — contrato de CRS y orden de ejes

**Estado:** **Aprobado arquitectónicamente** (2026-11-01), incluidas las pruebas AX. Revisión 2. **No modifica** `spec/`: el texto propuesto se
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
| F-16 | Sin CRS declarado, DuckDB exporta `geoarrow.wkb` con metadatos `{}`. Con un CRS que no es PROJJSON (p. ej. `ST_SetCRS(…, 'FOO:123')`) lo exporta como `{"crs_type":"authority_code","crs":"FOO:123"}`, sin validarlo | Linux, DuckDB 1.5.6 y 2.0.0 | `docs/evidence/g0/c4/qgis_crs_unknown.py` |
| F-17 | QGIS no reconoce `FOO:123` (`isValid() = False`) ni inventa un CRS; en ambos casos la capa queda con CRS no válido y conserva x = −68,15, y = −16,5 | Linux, QGIS 3.44.14 y 4.2.3, DuckDB 2.0.0 | `docs/evidence/g0/c4/result_crs_q344.json`, `result_crs_q42.json` |
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
4. **CRS desde GeoArrow.** El CRS de la capa se obtiene de los metadatos GeoArrow (PROJJSON o código de
   autoridad → `QgsCoordinateReferenceSystem.createFromUserInput`), según ADR-0008. Sin CRS declarado, rige
   el orden de preferencia actual de §4. Nunca se asume EPSG:4326.
4 bis. **CRS desconocido.** Si DuckDB declara un CRS que QGIS no reconoce, o no declara ninguno, GeoDuck:
   - no lo sustituye por otro CRS, ni por EPSG:4326, ni por el CRS del proyecto;
   - no publica la capa sin una decisión del usuario: le ofrece elegir un CRS (§4, punto 3) o continuar con
     CRS desconocido y una advertencia visible (§4, punto 4);
   - conserva el texto original declarado (p. ej. `FOO:123`) en el mensaje y en el registro, para que sea
     trazable;
   - nunca modifica las coordenadas, ocurra lo que ocurra con el CRS.
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
- §8, añadir a las pruebas obligatorias. Todas usan el mismo punto de referencia,
  `POINT(-68.15 -16.5)` (longitud, latitud de La Paz), y comparan con tolerancia de 1e-9 en grados y 0,01 m en
  metros. Cada prueba verifica **las dos cosas**: coordenadas y CRS.

| ID | Caso | CRS esperado en la capa QGIS | Coordenadas esperadas | Además |
|---|---|---|---|---|
| **AX-1a** | `GEOMETRY('OGC:CRS84')` | válido, `authid = OGC:CRS84` | x = −68,15, y = −16,5 (sin reordenar) | QGIS → EPSG:32719 = `590716.04, 8175564.99` |
| **AX-1b** | `EPSG:4326` con `spatial` | válido, `authid = EPSG:4326` | x = −68,15, y = −16,5, aunque `hasAxisInverted() = True` | QGIS → EPSG:32719 = `590716.04, 8175564.99` |
| **AX-1c** | `ST_Transform(…, 'EPSG:4326', 'EPSG:32719', true)` en DuckDB | válido, `authid = EPSG:32719` | `590716.04, 8175564.99` | igual que AX-1a/b transformado por QGIS |
| **AX-2** | `geometry_always_xy` en `true`, `false` y sin fijar | — | — | valor mostrado = valor de `duckdb_settings()`; antes y después de cada operación de GeoDuck el valor es el mismo (GeoDuck no lo modifica) |
| **AX-3** | `ST_Transform` sin orden declarado, DuckDB 2.0 con el ajuste sin fijar | — (no se crea capa) | — | error de DuckDB presentado como error SQL del usuario; sin reintentos; `geometry_always_xy` sigue sin fijar |
| **AX-4a** | Sin CRS declarado (metadatos GeoArrow `{}`) | no válido; GeoDuck **no** asigna ninguno | x = −68,15, y = −16,5 | la capa no se publica sin decisión del usuario; si continúa, la advertencia es visible |
| **AX-4b** | CRS declarado desconocido para QGIS (`FOO:123`) | no válido; GeoDuck **no** lo sustituye | x = −68,15, y = −16,5 | el mensaje muestra `FOO:123`; misma decisión del usuario que AX-4a |
| **AX-4c** | CRS desconocido y el usuario elige `EPSG:4326` | válido, `authid = EPSG:4326` | x = −68,15, y = −16,5 (elegir un CRS **etiqueta**, no transforma) | — |

  Hechos ya comprobados que sostienen estos valores: AX-1a y AX-1b con `qgis_axis.py` (QGIS 3.44 y 4.2);
  AX-1c en Windows (`../windows/win11-qgis-3.34.15/` §4); el comportamiento de QGIS en AX-4a y AX-4b con
  `qgis_crs_unknown.py`. AX-2, AX-3 y AX-4c dependen de la UI y del puente de G3/G4.

## 6. Consecuencias

- Pro: comportamiento predecible e idéntico en DuckDB 1.5, 2.0 y 2.1; GeoDuck no altera la sesión del
  usuario.
- Pro: con DuckDB 2.1 no hará falta ningún cambio: el valor por defecto cambia en DuckDB, no en GeoDuck.
- Contra: si el SQL del usuario genera coordenadas en orden latitud-longitud, la capa aparecerá desplazada
  en QGIS. GeoDuck lo explica en la documentación, pero no lo corrige ni lo detecta.
- Dependencia: el punto 3 necesita el diagnóstico de `spatial` (existente) y, en G4, la UI de selección
  espacial.

## 7. Preguntas para el arquitecto

1. ~~¿Se aprueba que GeoDuck **no** fije `geometry_always_xy`, ni siquiera a `true` para anticipar DuckDB
   2.1?~~ **Resuelta** (2026-11-01): aprobado, sin cambios silenciosos de configuración.
2. **Abierta.** ¿El valor efectivo debe mostrarse solo en el diagnóstico (G0/G4) o también en cada resultado espacial?
3. ~~AX-4: ¿se aprueba que, con CRS desconocido, la capa no se publique sin una decisión explícita del
   usuario?~~ **Resuelta** (2026-11-01): aprobada con las pruebas AX.

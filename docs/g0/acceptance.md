# G0 · Documento de aceptación (propuesta de cierre)

**Estado:** Propuesta para aprobación del propietario y del arquitecto (2026-11-01). G0 **no** está cerrado
hasta esa aprobación (roadmap §1: «cada gate se cierra solo cuando pasan pruebas e2e relevantes y se aprueba
su documento de aceptación»). No se ha creado ningún tag ni release.

**Commit verificado:** `e6a75a0` en `main` (merge del PR #33).

## 1. Requisitos de G0

| Requisito | Prueba de aceptación | Evidencia | Resultado |
|---|---|---|---|
| GD-BOOT-001 · el complemento aparece en QGIS y abre el panel | AT-BOOT-001 | `tests/qgis/test_plugin.py` en QGIS 3.44.14 (Qt5) y 4.2.3 (Qt6), Linux sin interfaz; prueba de humo en Windows 11 + QGIS 3.34.15 | Cumple |
| GD-BOOT-002 · diagnóstico con mensajes accionables | AT-BOOT-002 | `tests/unit/test_diagnostics.py` (incluye PyArrow ≥ 18.1.0, NumPy 1/2, DLL de Windows, *site* de usuario, origen de `duckdb`) y la variante en la UI de `tests/qgis/test_plugin.py`; diagnóstico real en Windows | Cumple |
| GD-SES-001 · sesión raíz `:memory:` | AT-SES-001 | `tests/engine/test_session_worker.py` con DuckDB 1.5.0, 1.5.6 y 2.0.0; ciclo iniciar/cerrar en el panel en Windows | Cumple |

**Gate de salida (roadmap §2): «QGIS 3/4 ancla cargan; duckdb/arrow/spatial validado».**

- QGIS 3 y 4 cargan el complemento: sí, en CI (QGIS 3.44.14 y 4.2.3, con DuckDB 1.5.0 y 2.0.0) y en Windows
  con QGIS 3.34.15.
- DuckDB, PyArrow y `spatial` validados: matriz de motor en CI (DuckDB 1.5.0, 1.5.6 y 2.0.0; Python 3.12 y
  3.14; PyArrow 18.1.0 y 25.0.1; NumPy 1.26.4) y diagnóstico de `spatial` verificado en Windows.

## 2. Verificación de `main` tras las fusiones

| Comprobación | Resultado |
|---|---|
| CI remoto sobre `e6a75a0` (14 jobs: lint, tipos, arquitectura, unitarias; 8 celdas de motor; 4 de PyQGIS; ZIP) | 14/14 en verde |
| `ruff check`, `ruff format --check`, `mypy` (núcleo estricto) | Sin errores |
| Pruebas unitarias, de arquitectura y de motor | 174 en verde con DuckDB 1.5.0, 1.5.6 y 2.0.0, y con PyArrow 18.1.0 + NumPy 1.26.4 |
| Regresiones | Ninguna. Antes de las fusiones había 160 pruebas; ahora hay 174. Solo cambiaron de parámetro dos casos de DuckDB 1.5.4, que pasó de «recomendada» a «soportada, no recomendada» (D5) |
| `spec/` | `tools/spec_sync.py --check`: la maestra y `manifest.json` coinciden con los archivos individuales |
| ZIP del complemento | Reproducible: dos construcciones dan el mismo SHA-256 |

## 3. Decisiones de G0 aprobadas

- D3 (QGIS 3.34 mínimo; prioridad de certificación 3.44 LTR y 4.2.x) y D5 (DuckDB 1.5.0 mínimo, 1.5.6
  recomendada, 2.x verificada).
- ADR-0006, 0007, 0009, 0010 y 0011, incorporados a `spec/docs/adr/`.
- C4 (CRS y orden de ejes) y C13 (estados de sesión e invalidación), incorporados a `spec/`.

## 4. Lo que queda abierto y no bloquea el cierre

Por decisión del arquitecto (2026-11-01), la certificación Windows es **trabajo de calidad que no bloquea
el desarrollo**.

| Tema | Estado | Seguimiento |
|---|---|---|
| Certificación Windows completa: suites en QGIS 3.44 LTR y 4.2.x (prioridad D3), DuckDB 1.5.x, regresión en 3.34 | Pendiente. Hoy solo hay prueba de humo en 3.34.15 + DuckDB 2.0.0 | #10 |
| Método de instalación definitivo en Windows | Pendiente | #10 |
| Spike G0-B: editor SQL nativo en PyQGIS 3/4 | Pendiente; lo necesita G2, no G1 | #11 |
| R11: convivencia con complementos que traen su propio DuckDB | El diagnóstico lo detecta; la política queda para G7 | ADR-0011 |
| ADR-0008 (GeoArrow) | Propuesto; se decide antes de G3 | — |
| Correo de `metadata.txt` | Marcador hasta que el propietario lo defina | — |

**Consecuencia honesta:** mientras #10 no termine, no se afirma compatibilidad certificada en Windows para
QGIS 3.44 ni 4.2. Las notas de cualquier release deben decirlo así.

## 5. Para aprobar

1. Cierre de G0 con lo pendiente de §4 como trabajo de calidad no bloqueante.
2. Tag y release `v0.1.0a1` (#12): requiere aprobación expresa aparte. Si se aprueba, el tag iría sobre
   `e6a75a0`, con notas que digan la compatibilidad exacta verificada.

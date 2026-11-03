# ADR-0011: convivencia con otros complementos que usan su propio DuckDB

**Estado:** Aceptado (dictamen del arquitecto, 2026-11-01)
**Relacionado:** ADR-0005 (compatibilidad), ADR-0009 (dependencias por matriz), `spec/docs/security.md`,
`spec/docs/technology.md` (Empaquetado); evidencia `docs/evidence/g0/windows/win11-qgis-3.34.15/` §5

## Contexto

En la prueba en Windows del 2026-11-01 (QGIS 3.34.15), el complemento **QDuckDB** estaba activo e
**incrusta su propia copia de DuckDB 1.4.4** en su carpeta (`plugins/qduckdb/embedded_external_libs/duckdb`).

Todos los complementos de QGIS comparten un mismo proceso y un mismo intérprete Python. En ese intérprete
solo puede haber **un** módulo `duckdb` cargado: el primero que se importa queda para todos. Se observaron
dos situaciones:

- Antes de instalar nada, `import duckdb` devolvía la 1.4.4 de QDuckDB, por debajo del mínimo de GeoDuck
  (1.5.0).
- Tras instalar `duckdb==2.0.0` en el *site* de usuario y reiniciar QGIS con QDuckDB activo, GeoDuck
  recibió la 2.0.0, y **QDuckDB pasó a ejecutarse con DuckDB 2.0.0** en lugar de su 1.4.4. No se verificó
  si QDuckDB funciona así.

Qué versión gana depende del orden de carga y de `sys.path`, que GeoDuck no controla. Es un riesgo de
convivencia (R11) con cualquier complemento que incruste o fije su propio DuckDB.

## Decisión

1. **GeoDuck no modifica ni reemplaza silenciosamente dependencias de otros complementos.** En concreto,
   GeoDuck nunca:
   - instala, actualiza ni desinstala paquetes por su cuenta (ya establecido: sin `pip` silencioso);
   - altera `sys.path`, `sys.modules` ni el orden de carga para imponer su versión de `duckdb`;
   - modifica, desactiva ni escribe en carpetas de otros complementos.
2. **GeoDuck diagnostica y explica.** El diagnóstico muestra la **versión efectiva** de DuckDB y **de dónde
   se cargó**. Si proviene de la carpeta de otro complemento, emite un aviso que nombra ese complemento
   (comprobación «Origen de DuckDB», PR #21). Si la versión efectiva está por debajo del mínimo, el
   diagnóstico falla y el panel no permite iniciar sesión, como con cualquier otra versión no soportada.
3. **La decisión es del usuario.** Las instrucciones de instalación de GeoDuck advierten que, si otro
   complemento usa su propio DuckDB, instalar uno en el entorno de QGIS puede cambiar la versión que ese
   complemento recibe. Antes de instalar, el usuario debe consultar el diagnóstico.
4. **Riesgo pendiente.** La convivencia con QDuckDB queda documentada como riesgo abierto. Toda solución
   que vaya más allá del diagnóstico requiere un ADR nuevo: coordinación con los mantenedores de QDuckDB,
   aislamiento del motor en un proceso aparte o un rango de versiones compatible acordado. Se reevaluará
   en G9 (Reliability & Distribution; renumerado el 2026-11-02 y el 2026-11-03).

## Alternativas descartadas por ahora

| Alternativa | Por qué no |
|---|---|
| Incrustar un DuckDB propio con otro nombre de módulo | La extensión nativa de DuckDB se registra como `duckdb`; renombrarla no es una vía soportada y duplicaría binarios en el ZIP, que no admite binarios (plugins.qgis.org) |
| Forzar la versión de GeoDuck manipulando `sys.path` o `sys.modules` | Reemplaza silenciosamente la dependencia de otro complemento: contradice la decisión 1 |
| Ejecutar DuckDB en un proceso separado | Cambia la arquitectura de sesión (ADR-0001, ADR-0006) y el transporte Arrow; fuera del alcance Alpha actual |
| Desactivar automáticamente el otro complemento | Actúa sobre la configuración del usuario sin su consentimiento |

## Consecuencias

- Pro: GeoDuck no rompe otros complementos por iniciativa propia y el usuario ve la causa real cuando
  hay un conflicto.
- Contra: con un complemento que incrusta un DuckDB antiguo, GeoDuck puede quedar inutilizable hasta que el
  usuario decida (desactivar ese complemento, o aceptar que reciba otra versión).
- La evidencia de certificación debe registrar qué complementos con DuckDB había activos en cada celda.

## Verificación

- `tests/unit/test_diagnostics.py`: aviso «Origen de DuckDB» con la ruta real observada en Windows
  (`plugins/qduckdb/embedded_external_libs/duckdb`) y en Linux; versión 1.4.4 → DuckDB en FAIL (PR #21).
- `tests/architecture`: ningún módulo de GeoDuck manipula `sys.path` ni `sys.modules`. Se añade la regla
  al aprobarse este ADR.
- Certificación Windows: repetir la celda con QDuckDB activo e inactivo y registrar la versión efectiva.

# Rendimiento en Windows: guía manual (#176; performance-spec §7)

<span>15 minutos</span>

Mide GeoDuck en **su** equipo con Windows, con el mismo banco que la CI. Los números se agregan a
[`docs/performance.md`](../performance.md) con el equipo anotado. No se comparan con otros equipos.

## 1. Antes de empezar

- QGIS instalado desde el MSI oficial (3.44.x LTR o 4.2.x) y GeoDuck funcionando (duckdb instalado; ver
  [windows.md](windows.md) §2).
- El repositorio en `C:\geoduck` (o el ZIP del repositorio, descomprimido ahí).
- Cierre QGIS y los programas pesados (navegador con muchas pestañas, antivirus en análisis).
- Enchufe el portátil a la corriente y elija el modo de energía «Mejor rendimiento».

## 2. Anote el equipo

`Configuración › Sistema › Información`: procesador, núcleos, RAM y tipo de disco (SSD o HDD). Y la versión de
QGIS y de DuckDB (GeoDuck › **?** › Diagnóstico del entorno).

## 3. Ejecute el banco

En PowerShell (cambie la carpeta de QGIS por la suya; el lanzador es `python-qgis-ltr.bat` en las LTR):

```powershell
& "C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" C:\geoduck\tools\perf\bench.py `
    --rows 1000000 --repeat 3 --out C:\geoduck-perf
```

Tarda unos 2 minutos y no muestra ventanas. Al terminar imprime una tabla y deja `bench-*.json` y `bench-*.md`
en `C:\geoduck-perf`. Repítalo una vez más (`--out C:\geoduck-perf\2`) para ver cuánto varía su equipo.

## 4. Opcional: 10 minutos de estrés

```powershell
& "C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" C:\geoduck\tools\perf\stress.py `
    --minutes 10 --rows 200000 --out C:\geoduck-perf\estres
```

## 5. Prueba en la interfaz (lo que se siente)

Con GeoDuck abierto en QGIS, cree la tabla de prueba en una consulta y ejecútela (Ctrl+Shift+Intro):

```sql
CREATE TABLE prueba AS SELECT range AS id, 'Sur' AS zona, random() * 1000 AS kwh,
    ST_Point(random() * 10, random() * 10) AS geom FROM range(1000000);
```

Anote sí o no en cada fila:

| Prueba | ¿Fluido? |
|---|---|
| Doble clic en `prueba`: la tabla se abre en menos de 1 s | |
| Desplazar con la barra hasta el final: sin pausas | |
| Filtro `kwh > 500`: responde en menos de 1 s | |
| Arrastrar `prueba` al mapa como **Conectada**: el mapa se dibuja y se puede mover | |
| Exportar a Parquet: termina y «Cancelar» detiene otra exportación al instante | |

## 6. Envíe los resultados

Comprima `C:\geoduck-perf`, con los datos del equipo (paso 2) y la tabla del paso 5, y adjúntelo al issue
#176 o entréguelo al implementador, que lo agrega a `docs/performance.md` sin editar los números.

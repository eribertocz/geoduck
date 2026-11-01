# Certificación en Windows 11 x64 — procedimiento reproducible (gate G0, GD-10/GD-11)

**Objetivo.** Producir, para cada celda de [`compat/matrix.toml`](../../compat/matrix.toml), evidencia
ejecutada en Windows real que permita marcarla `certificado`, `conocido con limitaciones` o
`incompatible`. Sin esta evidencia el gate G0 **no** se cierra (spec/docs/compatibility-distribution.md §6).

El procedimiento también resuelve el spike **G0-A** (método de instalación de dependencias) y **G0-B**
(editor SQL nativo).

## 1. Requisitos del entorno

| Requisito | Detalle |
|---|---|
| Sistema | Windows 11 x64, actualizado, en una VM o equipo que pueda restaurarse (instantánea antes de empezar) |
| Cuenta | Usuario administrador local (solo el método M1 lo exige) |
| Recursos | 8 GB de RAM y 15 GB libres |
| QGIS | Instaladores MSI oficiales de [qgis.org/download](https://qgis.org/download/): **3.44.x LTR** y **4.2.3** (y **4.4.x** si está publicada, decisión D3). Instalados lado a lado en sus carpetas por defecto |
| Red | Salida HTTPS a `pypi.org`, `files.pythonhosted.org`, `github.com` y, para spatial, `extensions.duckdb.org` |
| Herramientas | PowerShell 5.1 o 7.x; Git para Windows (o descargar el repositorio como ZIP) |
| Repositorio | `eribertocz/geoduck` en el commit que se certifica (anotarlo) |
| Variables | **Sin** `PYTHONPATH` ni `PYTHONHOME` globales. Anote si existe `%APPDATA%\Python` (paquetes de usuario: issue QGIS #63733) |

Antes de empezar, desactive la ejecución restringida solo para la sesión:
`Set-ExecutionPolicy -Scope Process Bypass`.

## 2. Métodos de instalación a comparar (spike G0-A)

El ZIP del complemento no puede incluir binarios (regla de plugins.qgis.org), así que `duckdb` y
`pyarrow` deben instalarse aparte. Todos los métodos usan `--no-deps` para **no** reemplazar la NumPy
de QGIS.

| Método | Dónde instala | Ventajas | Riesgos a observar |
|---|---|---|---|
| M1 | Dentro del Python de QGIS (`apps\Python312\Lib\site-packages`) | Simple; visible para todo QGIS | Requiere administrador; se pierde al actualizar QGIS; puede afectar a otros complementos |
| M2 | Carpeta propia (por defecto `%LOCALAPPDATA%\GeoDuck\deps\<celda>`) | Sin administrador; no modifica QGIS; reversible borrando una carpeta | Requiere que GeoDuck añada la carpeta a `sys.path` (necesitaría ADR); DLL cargadas desde fuera de QGIS |
| M3 | Site de usuario (`pip --user`) | Sin administrador | Conflictos conocidos con otros Python 3.12 del usuario (#63733); se espera descartarlo |

La elección del método principal es una decisión del propietario con base en esta evidencia.

## 3. Celdas a ejecutar

Para cada QGIS instalado × cada método (M1, M2, M3) = 6 ejecuciones (9 con 4.4.x). Cada ejecución
cubre las tres versiones de DuckDB cambiando el archivo de restricciones:

| Archivo de restricciones | Contenido |
|---|---|
| `constraints/win-qgis-3.44-py312.txt` | `duckdb==2.0.0`, `pyarrow==25.0.1` |
| copia local con `duckdb==1.5.0` | mínimo soportado |
| copia local con `duckdb==1.5.6` | última 1.5.x |

Para QGIS 4.x, cree la copia correspondiente de `constraints/win-qgis-4.2.txt` tras ver en `facts.json`
qué Python y NumPy trae (si NumPy ≥ 2, añada también una pasada con `pyarrow==26.0.0`).

## 4. Pasos

1. **Instantánea** de la VM. Anote la edición de Windows (`winver`) y el commit de GeoDuck.
2. **Instale QGIS** desde los MSI. Abra cada QGIS una vez y ciérrelo (crea el perfil).
3. **Obtenga el repositorio** en `C:\geoduck` (por ejemplo, `git clone https://github.com/eribertocz/geoduck C:\geoduck`).
4. **Ejecute el script automatizado** desde `C:\geoduck\tools\windows`, una vez por celda:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   cd C:\geoduck\tools\windows
   .\Invoke-GeoDuckCertification.ps1 -QgisRoot "C:\Program Files\QGIS 3.44.15" -Method M2 `
       -Constraints ..\..\constraints\win-qgis-3.44-py312.txt -OutDir C:\geoduck-cert -RunTestSuites
   ```

   El script localiza `bin\python-qgis*.bat`, registra `facts.json`, instala con el método indicado,
   ejecuta `tools\verify_env.py` y las suites `tests\unit`, `tests\architecture`, `tests\engine` y
   `tests\qgis` con **el Python de QGIS**, y deja `report.json`, `report.txt`, `pytest.xml`,
   `transcript.txt` y `SHA256SUMS.txt` en `C:\geoduck-cert\<celda>`.

   Antes de pasar a otro método, ejecute el comando de reversión que imprime el script.

5. **Prueba manual E2E en la GUI** (una vez por versión de QGIS, con el método que haya resultado
   APTO):
   1. Construya el ZIP: `python tools\build_zip.py` (o use el artefacto `geoduck-plugin-zip` del CI).
   2. QGIS → Complementos → Administrar e instalar → Instalar a partir de ZIP → `geoduck-0.1.0a1.zip`.
   3. Active «Mostrar también complementos experimentales» si no aparece.
   4. Abra el panel con el botón GeoDuck de la barra Base de datos. Capture la pantalla.
   5. Pulse «Diagnóstico del entorno…» → «Copiar» y pegue el informe en `diagnostico_gui.txt`.
   6. Pulse «Iniciar sesión» → el estado debe pasar a «Lista»; «Cerrar sesión» → «Sin sesión».
   7. Con la sesión iniciada, cierre QGIS: debe cerrarse en menos de 10 s sin errores.
   8. Pruebe el tema oscuro (Configuración → Opciones → General → Tema de la interfaz) y una escala
      de pantalla de 150 %; capture el panel.
   9. Desinstale el complemento desde el administrador y reinicie QGIS: no deben quedar errores.
6. **Spatial**: siga [`spatial.md`](spatial.md) en al menos una celda por versión de QGIS.
7. **Restaure la instantánea** antes de la siguiente versión de QGIS si los métodos dejaron residuos.

## 5. Criterios de aceptación por celda

| Comprobación | Fuente | Obligatoria |
|---|---|---|
| `report.json` → `resultado: APTO` | `verify_env.py` | Sí |
| `pytest.xml` sin fallos (se admiten `skipped` justificados) | suites del repositorio | Sí |
| Panel abre, sesión inicia y cierra, QGIS cierra limpio | paso 5 | Sí |
| Diagnóstico de la GUI sin `FAIL` | paso 5.5 | Sí |
| Bloqueo liberado tras `DETACH` (proceso externo) | `verify_env.py` | Sí (semántica Windows de bloqueos) |
| Spatial carga y transforma EPSG | `spatial.md` | No para G0; sí para G4 |
| Tema oscuro y 150 % legibles | capturas | Sí (GD-UX-001 parcial) |

Una celda es **certificada** solo si todas las obligatorias pasan con las tres versiones de DuckDB.
Si alguna falla, la celda queda `conocido con limitaciones` (con el defecto documentado y aceptado por el
propietario) o `incompatible`.

## 6. Entrega de resultados

Comprima `C:\geoduck-cert` y adjúntelo al issue GD-10 (o entréguelo al implementador). El implementador:

1. Copia los resultados a `docs/evidence/g0/windows/<celda>/` sin editarlos.
2. Actualiza `compat/matrix.toml` y `constraints/` con los valores observados.
3. Redacta el ADR del método de instalación elegido (G0-A) para aprobación del propietario.
4. Prepara las notas de versión de `0.1.0a1` con la matriz exacta. El tag y la release requieren su
   aprobación expresa.

## 7. Limitaciones conocidas del procedimiento

- `Invoke-GeoDuckCertification.ps1` se validó con el parser de PowerShell 7.4 y se ejecutó de punta a
  punta en Linux con PowerShell 7.4.6, un lanzador simulado que delega en el Python de QGIS 3.44.14
  (conda-forge) y el método M2: `verify_env` APTO y 115 pruebas en verde. **No se ha ejecutado en
  Windows**: rutas, `python-qgis*.bat`, permisos de M1 y la semántica de bloqueos de archivos se validan
  en la primera ejecución real, y cualquier ajuste se registra en el informe.
- El nombre exacto del lanzador (`python-qgis.bat` / `python-qgis-ltr.bat`) se detecta en tiempo de
  ejecución; si no existe en su instalación, el script se detiene con un mensaje explícito.

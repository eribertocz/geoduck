# Abrir, crear y cerrar bases

<span class="gd-time">3 minutos</span>

## Abrir una base

1. «+» en el explorador › **Abrir base…**
2. Elige el archivo (`.duckdb`, `.ddb` o `.db`).
3. Si la quieres solo para leer, marca **Solo lectura**.

El nombre de la base en el explorador es el del archivo (sin la extensión). Si ya hay una con ese nombre,
GeoDuck propone otro.

## Crear una base

- **Crear base…**: un archivo nuevo. GeoDuck nunca sobrescribe uno que ya existe.
- **Nueva base en memoria…**: sin archivo. Se pierde al cerrar la sesión, salvo que la guardes como archivo.

## Usar como base activa

Clic derecho en una base › **Usar como base activa**. También desde «Base activa ▾» en el editor o con
**Ctrl+K**. Las consultas se ejecutan en la base activa.

## Cerrar una base

Clic derecho › **Cerrar base**. No se puede cerrar la base activa ni la última: el menú lo dice en gris.

- Si tiene **capas Conectadas**, quedan «no disponibles» y vuelven con **Abrir de nuevo**.
- Si es **en memoria** y tiene capas, GeoDuck te pide guardarla antes como archivo.
- Si hay **cambios sin guardar** en una capa, primero guárdalos o descártalos en QGIS.

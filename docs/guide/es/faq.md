# Preguntas frecuentes

## ¿Qué versión de DuckDB necesito?

DuckDB 1.5.4 o posterior (recomendada 1.5.6, o 2.x), instalada en el Python de QGIS. **? › Diagnóstico del
entorno** lo comprueba y dice cómo instalarla.

## ¿Mis datos salen de mi equipo?

No. Todo corre dentro de QGIS. Solo se descarga la extensión espacial la primera vez, desde el repositorio
oficial.

## ¿Puedo usar GeoDuck sin internet?

Sí. Sin la extensión espacial instalada, GeoDuck funciona igual, pero sin funciones espaciales. Puedes
instalarla desde un archivo (ver [Errores frecuentes](errors.md#spatial)).

## ¿Dónde se guardan mis consultas?

Donde las guardes con Ctrl+S (archivos `.sql`). GeoDuck además guarda copias de recuperación mientras escribes.

## ¿Puedo abrir la misma base desde otro programa?

Sí, si todos la abren en **Solo lectura**. Un programa que la abre en escritura la bloquea para los demás.

## ¿Qué pasa con mis capas si cierro la sesión?

Las capas **Copia** siguen igual. Las **Conectadas** quedan «no disponibles» y vuelven al iniciar GeoDuck y
abrir su base (o solas, al abrir el proyecto).

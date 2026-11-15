# Importar archivos

<span class="gd-time">2 minutos</span>

1. Arrastra los archivos sobre una base del explorador, o «+» › **Importar archivos…**
2. Revisa los nombres de las tablas y pulsa **Enviar**.

GeoDuck lee directo CSV, Parquet, JSON y, con la extensión espacial, GeoPackage, Shapefile, GeoJSON y otros
formatos de GDAL.

## Consultar sin importar

Suelta un archivo en el **editor**: GeoDuck escribe `FROM 'ruta';` (o `FROM ST_Read('ruta');`) sin ejecutar.
Así consultas el archivo sin crear una tabla:

```sql
SELECT * FROM read_csv('C:/datos/lecturas.csv', delim = ';');
```

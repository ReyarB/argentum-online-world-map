# Argentum Online World Map

Proyecto independiente para generar y publicar el mapa mundial interactivo de
Argentum Online. Lee los datos oficiales desde el repositorio `Recursos`, pero
no guarda herramientas ni salidas web dentro de ese repositorio.

## Separación de responsabilidades

- `Recursos`: fuente de mapas, DAT, gráficos y configuración del juego.
- Este repositorio: generador, interfaz web, validaciones y documentación.
- `workspace/`: salida local del World Editor (no versionada).
- `workspace/map_content.sqlite`: índice generado por el WE (no versionado).
- `dist-web/`: sitio listo para publicar (no versionado en la rama principal).

La aplicación web resultante es estática. El usuario final solo necesita un
navegador; no necesita Python, SQLite ni el World Editor.

Los traslados internos se publican como entradas visibles. Un doble clic abre
`interiores.html`, una página independiente que permite recorrer dungeons,
sótanos y demás interiores mediante las coordenadas reales de
`map_content.sqlite`, y regresar después al mapa de superficie. Los interiores
conectados por sus bordes se acomodan como un submundo continuo, con búsqueda,
zoom, arrastre, selección de mapas, capas, contadores, preferencias F1 y la
opción de mostrar u ocultar traslados. El constructor incluye
automáticamente los minimapas interiores alcanzables sin incorporarlos a la
grilla del mundo.

## Requisitos

- Python 3.12 o posterior.
- Pillow.
- Un checkout local actualizado de `Recursos`.
- `map_content.sqlite` generado por el World Editor o la auditoría de mapas.
- Minimapas extendidos generados por el World Editor. Cada PNG contiene el
  centro del mapa y, en sus márgenes transparentes, los gráficos que cruzan
  hacia mapas vecinos.

```powershell
py -3.12 -m pip install -r requirements.txt
```

## Migración inicial

La primera vez, coloque los minimapas web antiguos de 592x640 en
`workspace/minimapas` y sus desbordes en `workspace/desbordes`, o genérelos con
el WE. Luego ejecute:

```powershell
py -3.12 scripts/migrate_workspace.py --resources ..\Recursos
```

`Recursos/Minimapas` contiene las imágenes de 100x100 usadas por el juego y no
se emplea como entrada para esta conversión. La migración conserva intacto
`Recursos`. Después de crear correctamente cada
PNG unificado, elimina únicamente las copias BMP y los desbordes antiguos del
`workspace` para que no vuelvan a tener prioridad durante la publicación.

Los WE activos escriben después directamente en `workspace/`. La ruta se puede
cambiar con el ajuste `paths/worldMapWorkspace` o con la variable de entorno
`AO_WORLD_MAP_WORKSPACE`.

## Construir el sitio

```powershell
py -3.12 scripts/build_web.py --resources ..\Recursos
```

La salida se escribe en `dist-web/`. Los BMP completos se convierten a WebP y
el navegador carga solamente los mapas visibles.

Por omisión se leen `workspace/minimapas` y `workspace/map_content.sqlite`.
`--map-assets` y `--database` permiten usar otra ubicación de forma explícita.
El constructor todavía acepta temporalmente el formato anterior compuesto por
un BMP base y `workspace/desbordes/`, y los combina en un único WebP al generar
el sitio.

## Ejecutar la herramienta visual

```powershell
py -3.12 src/mapa_mundo.py `
  --base-dir ..\Recursos `
  --database .\workspace\map_content.sqlite `
  --web-output .\dist-web
```

La ventana continúa editando `mapsworlddata.dat` y exportando `world1.png`,
`world2.png` y `world3.png` a sus rutas oficiales de `Recursos`, pero la página
web se genera exclusivamente en `dist-web/`.

Para la vista de 27×27 y la exportación del cliente se revisan las carpetas
`argentum-herramientas/tools_ReyarB/render`. La herramienta descarta las
copias uniformes, elige la copia válida más reciente y, cuando no usa la ruta
principal, lo informa como `Respaldo válido` en la barra inferior.

## Probar la página

1. Abrir `dist-web/index.html` (o `index.htm` para compatibilidad local).
2. Probar zoom, arrastre, búsqueda y filtros; marcar varias casillas, recargar y
   verificar que conserven su estado.
3. Dejar el puntero un segundo sobre NPC, recurso, portal o punto de interés.
4. Hacer doble clic sobre un mapa y verificar sus detalles.
5. En el mapa 32, hacer doble clic sobre el marcador de traslado hacia
   `Mapa 397 - Catacumba Residencial III` y recorrer al menos uno de sus
   traslados.
6. En el mapa 34, abrir `Mapa 168 - Newbie Dungeon` y verificar que se navegue
   a `interiores.html`, con la vista unida 2×2 de los mapas 37, 167, 168 y 264,
   incluyendo búsqueda, zoom, capas, traslados y el regreso a `index.html`.
7. Presionar `F1`, cambiar la configuración, recargar y verificar persistencia.
8. Restaurar los valores predeterminados.

Valores predeterminados:

- Vista inicial centrada con zoom al 25 %.
- Caras `NpcFaceGrh`: 30 % (ajustable entre 5 % y 80 % con F1).
- Cuerpos `Body`: 70 %.
- Objetos y recursos: 100 %.
- Nombres de áreas: 260 % (ajustable entre 50 % y 350 % con F1).
- Aviso contextual: 1 segundo.
- Fuente: fuente gráfica 8 del cliente VB6.
- Panel del mapa compacto: muestra contadores, pero oculta los listados
  detallados. Se pueden habilitar con F1.

Las preferencias de F1 y las casillas del panel se guardan en el almacenamiento
local del navegador. Son independientes para cada navegador y computadora, y no
se envían al servidor.

## Regla para contribuir

La fuente de verdad es `src/mapa_mundo.py`. No se deben corregir problemas
editando únicamente `dist-web/index.htm`, porque ese archivo se regenera.

Antes de confirmar cambios:

```powershell
py -3.12 -m py_compile src/mapa_mundo.py scripts/build_web.py scripts/migrate_workspace.py
py -3.12 scripts/build_web.py --resources ..\Recursos
node scripts/validate_generated.js dist-web/index.html
```

El constructor falla si falta un mapa, la fuente gráfica o una dependencia
necesaria para la publicación.

## Publicación

`dist-web/` es el único directorio que debe enviarse al alojamiento estático.
La rama principal conserva solo código y documentación; la rama `gh-pages`
contiene exclusivamente la última salida publicada. GitHub Pages sirve esa
rama desde su raíz.

Para publicar una actualización, primero reconstruya y valide `dist-web/` con
los comandos anteriores. Después reemplace el contenido de `gh-pages` por esa
salida. No confirme `workspace/` ni `dist-web/` en `main`.


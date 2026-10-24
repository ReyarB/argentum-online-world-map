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

## Requisitos

- Python 3.12 o posterior.
- Pillow.
- Un checkout local actualizado de `Recursos`.
- `map_content.sqlite` generado por el World Editor o la auditoría de mapas.
- Minimapas completos y desbordes generados por el World Editor.

```powershell
py -3.12 -m pip install -r requirements.txt
```

## Migración inicial

La primera vez, copie los artefactos antiguos sin borrar todavía el origen:

```powershell
py -3.12 scripts/migrate_workspace.py --resources ..\Recursos
```

Los WE activos escriben después directamente en `workspace/`. La ruta se puede
cambiar con el ajuste `paths/worldMapWorkspace` o con la variable de entorno
`AO_WORLD_MAP_WORKSPACE`.

## Construir el sitio

```powershell
py -3.12 scripts/build_web.py --resources ..\Recursos
```

La salida se escribe en `dist-web/`. Los BMP completos se convierten a WebP y
el navegador carga solamente los mapas visibles.

Por omisión se leen `workspace/minimapas`, `workspace/desbordes` y
`workspace/map_content.sqlite`. `--map-assets` y `--database` permiten usar
otra ubicación de forma explícita.

## Ejecutar la herramienta visual

```powershell
py -3.12 src/mapa_mundo.py `
  --base-dir ..\Recursos `
  --database .\workspace\map_content.sqlite `
  --web-output .\dist-web
```

La ventana continúa editando `mapsworlddata.dat` y exportando `world1.png` y
`world2.png` a sus rutas oficiales de `Recursos`, pero la página web se genera
exclusivamente en `dist-web/`.

## Probar la página

1. Abrir `dist-web/index.htm`.
2. Probar zoom, arrastre, búsqueda y filtros.
3. Dejar el puntero un segundo sobre NPC, recurso, portal o punto de interés.
4. Hacer doble clic sobre un mapa y verificar sus detalles.
5. Presionar `F1`, cambiar la configuración, recargar y verificar persistencia.
6. Restaurar los valores predeterminados.

Valores predeterminados:

- Caras `NpcFaceGrh`: 15 %.
- Cuerpos `Body`: 70 %.
- Objetos y recursos: 100 %.
- Nombres de áreas: 100 %.
- Aviso contextual: 1 segundo.
- Fuente: fuente gráfica 8 del cliente VB6.

## Regla para contribuir

La fuente de verdad es `src/mapa_mundo.py`. No se deben corregir problemas
editando únicamente `dist-web/index.htm`, porque ese archivo se regenera.

Antes de confirmar cambios:

```powershell
py -3.12 -m py_compile src/mapa_mundo.py scripts/build_web.py scripts/migrate_workspace.py
py -3.12 scripts/build_web.py --resources ..\Recursos
node scripts/validate_generated.js dist-web/index.htm
```

El constructor falla si falta un mapa, la fuente gráfica o una dependencia
necesaria para la publicación.

## Publicación

`dist-web/` es el único directorio que debe enviarse al alojamiento estático.
La rama principal conserva solo código y documentación. La publicación
automática se agregará cuando el WE produzca `workspace/` y la base SQLite fuera
de `Recursos`.


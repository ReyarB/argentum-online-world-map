#!/usr/bin/env python3
"""Genera un sitio web autónomo sin escribir dentro de Recursos."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = PROJECT_ROOT / "src" / "mapa_mundo.py"
BASE_MAP_SIZE = (592, 640)


def load_generator():
    spec = importlib.util.spec_from_file_location("world_map_generator", SOURCE_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {SOURCE_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def safe_output(path: Path, resources: Path) -> Path:
    output = path.resolve()
    if output in {PROJECT_ROOT.resolve(), resources.resolve()}:
        raise ValueError("La salida no puede ser la raíz del proyecto ni Recursos")
    if resources.resolve() in output.parents:
        raise ValueError("La salida web no puede estar dentro de Recursos")
    return output


def recreate_directory(path: Path, output_root: Path) -> None:
    resolved = path.resolve()
    if output_root.resolve() not in resolved.parents:
        raise ValueError(f"Directorio generado fuera de la salida: {resolved}")
    if resolved.is_dir():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def find_map_image(directory: Path, map_id: int, suffix: str) -> Path | None:
    for stem in (f"Mapa{map_id}", f"mapa{map_id}"):
        candidate = directory / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def extended_map_image(source: Path, overflows: Path, map_id: int) -> tuple[Image.Image, str] | None:
    unified = find_map_image(source, map_id, ".png")
    if unified is not None:
        with Image.open(unified) as image:
            # The old workspace can also contain 200x216 composed-world PNGs
            # with the same stem. Only an alpha image large enough to contain
            # the canonical 592x640 center is a unified extended minimap.
            if (image.width >= BASE_MAP_SIZE[0] and image.height >= BASE_MAP_SIZE[1]
                    and (image.mode in {"RGBA", "LA"} or "transparency" in image.info)):
                if ((image.width - BASE_MAP_SIZE[0]) % 2
                        or (image.height - BASE_MAP_SIZE[1]) % 2):
                    raise RuntimeError(f"Minimapa extendido descentrado: {unified}")
                return image.convert("RGBA"), "unified"

    base_path = find_map_image(source, map_id, ".bmp")
    if base_path is None:
        return None
    with Image.open(base_path) as image:
        base = image.convert("RGBA")

    overflow_path = find_map_image(overflows, map_id, ".png")
    if overflow_path is None:
        return base, "base-only"
    with Image.open(overflow_path) as image:
        overflow = image.convert("RGBA")
    if overflow.width < base.width or overflow.height < base.height:
        raise RuntimeError(f"Desborde menor que el minimapa base: {overflow_path}")
    delta_x = overflow.width - base.width
    delta_y = overflow.height - base.height
    if delta_x % 2 or delta_y % 2:
        raise RuntimeError(f"Desborde descentrado respecto del minimapa base: {overflow_path}")
    combined = Image.new("RGBA", overflow.size, (0, 0, 0, 0))
    combined.alpha_composite(base, (delta_x // 2, delta_y // 2))
    combined.alpha_composite(overflow)
    return combined, "legacy-merged"


def convert_maps(source: Path, overflows: Path, target: Path,
                 map_ids: set[int], quality: int) -> dict[str, int]:
    recreate_directory(target, target.parent)
    stats = {"converted_maps": 0, "unified_sources": 0,
             "legacy_merged_sources": 0, "base_only_sources": 0}
    for map_id in sorted(map_ids):
        result = extended_map_image(source, overflows, map_id)
        if result is None:
            continue
        image, source_kind = result
        # Method 4 keeps practically the same size/quality as method 6 for the
        # extended alpha images while making a complete rebuild several times
        # faster on developer machines.
        image.save(target / f"Mapa{map_id}.webp", "WEBP", quality=quality, method=4)
        stats["converted_maps"] += 1
        stats[f"{source_kind.replace('-', '_')}_sources"] += 1
    return stats


def copy_runtime_assets(resources: Path, output: Path) -> None:
    graphics_target = output / "assets" / "graphics"
    fonts_target = output / "assets" / "fonts"
    graphics_target.mkdir(parents=True, exist_ok=True)
    fonts_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resources / "Graficos" / "19054.png", graphics_target / "19054.png")
    shutil.copy2(
        resources / "OUTPUT" / "Alegreya Sans AO.ttf",
        fonts_target / "Alegreya Sans AO.ttf",
    )


def validate_output(output: Path, map_ids: set[int]) -> dict[str, int]:
    required = [
        output / "index.htm",
        output / "index.html",
        output / "assets" / "graphics" / "19054.png",
        output / "assets" / "fonts" / "Alegreya Sans AO.ttf",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    missing_maps = [
        map_id for map_id in map_ids if not (output / "minimapas" / f"Mapa{map_id}.webp").is_file()
    ]
    if missing or missing_maps:
        detail = "\n".join(missing + [f"Mapa sin imagen: {item}" for item in missing_maps[:30]])
        raise RuntimeError(f"Salida web incompleta:\n{detail}")
    files = [path for path in output.rglob("*") if path.is_file()]
    return {"files": len(files), "bytes": sum(path.stat().st_size for path in files)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye el mapa mundial web independiente")
    parser.add_argument(
        "--resources",
        type=Path,
        default=PROJECT_ROOT.parent / "Recursos",
        help="Ruta al repositorio Recursos",
    )
    parser.add_argument(
        "--map-assets",
        type=Path,
        default=None,
        help="Carpeta con minimapas extendidos generados por el WE",
    )
    parser.add_argument("--database", type=Path, default=None, help="Ruta a map_content.sqlite")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "dist-web")
    parser.add_argument("--quality", type=int, default=88, choices=range(70, 96))
    args = parser.parse_args()

    resources = args.resources.resolve()
    output = safe_output(args.output, resources)
    workspace = PROJECT_ROOT / "workspace"
    map_assets = (args.map_assets or workspace).resolve()
    database = (args.database or workspace / "map_content.sqlite").resolve()
    world_data_path = resources / "init" / "mapsworlddata.dat"

    for required in [resources / "Dat", resources / "Mapas", world_data_path, database]:
        if not required.exists():
            raise FileNotFoundError(required)

    module = load_generator()
    data = module.WorldData(world_data_path)
    data.load()
    if not data.worlds:
        raise RuntimeError("mapsworlddata.dat no contiene mundos")
    placed_map_ids = {
        map_id
        for map_id in data.worlds[0].map_indices
        if map_id > 0 and map_id != module.EMPTY_TILE
    }

    output.mkdir(parents=True, exist_ok=True)
    conversion_stats = convert_maps(
        map_assets / "minimapas", map_assets / "desbordes",
        output / "minimapas", placed_map_ids, args.quality)
    obsolete_overflows = output / "desbordes"
    if obsolete_overflows.is_dir():
        shutil.rmtree(obsolete_overflows)
    copy_runtime_assets(resources, output)

    app = object.__new__(module.MapaMundoApp)
    app.base_dir = resources
    app.web_output_dir = output
    app.database_file = database
    app.data = data
    index_path = app.write_world_index()
    shutil.copy2(index_path, output / "index.html")
    stats = validate_output(output, placed_map_ids)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resources": str(resources),
        "maps": len(placed_map_ids),
        **conversion_stats,
        **stats,
    }
    (output / "build-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(index_path)
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

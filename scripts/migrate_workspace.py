"""Copia, sin borrar el origen, los artefactos web antiguos desde Recursos."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_MAP_SIZE = (592, 640)


def migrate_minimaps(
    source: Path, overflows: Path, target: Path
) -> tuple[int, int, set[str]]:
    if not source.is_dir():
        raise FileNotFoundError(source)
    target.mkdir(parents=True, exist_ok=True)
    migrated = 0
    merged = 0
    migrated_stems: set[str] = set()
    base_paths = sorted(source.glob("*.bmp"))
    known_stems = {path.stem.lower() for path in base_paths}
    for png_path in sorted(source.glob("*.png")):
        if png_path.stem.lower() in known_stems:
            continue
        with Image.open(png_path) as image:
            is_unified = (image.width >= BASE_MAP_SIZE[0]
                          and image.height >= BASE_MAP_SIZE[1]
                          and (image.mode in {"RGBA", "LA"}
                               or "transparency" in image.info))
        if is_unified:
            base_paths.append(png_path)
    for base_path in base_paths:
        with Image.open(base_path) as image:
            base = image.convert("RGBA")
        overflow_path = overflows / f"{base_path.stem}.png"
        if not overflow_path.is_file():
            overflow_path = overflows / f"{base_path.stem.lower()}.png"
        if base_path.suffix.lower() == ".bmp" and overflow_path.is_file():
            with Image.open(overflow_path) as image:
                overflow = image.convert("RGBA")
            delta_x = overflow.width - base.width
            delta_y = overflow.height - base.height
            if delta_x < 0 or delta_y < 0 or delta_x % 2 or delta_y % 2:
                raise RuntimeError(f"Desborde incompatible: {overflow_path}")
            combined = Image.new("RGBA", overflow.size, (0, 0, 0, 0))
            combined.alpha_composite(base, (delta_x // 2, delta_y // 2))
            combined.alpha_composite(overflow)
            base = combined
            merged += 1
        output_path = target / f"{base_path.stem}.png"
        base.save(output_path, "PNG", optimize=True)
        legacy_target = target / f"{base_path.stem}.bmp"
        if base_path.suffix.lower() == ".bmp":
            if base_path.parent.resolve() == target.resolve():
                base_path.unlink()
            elif (legacy_target.is_file()
                  and legacy_target.resolve() != base_path.resolve()):
                legacy_target.unlink()
        migrated += 1
        migrated_stems.add(base_path.stem.lower())
    return migrated, merged, migrated_stems


def remove_legacy_workspace_overflows(
    overflow_directory: Path, migrated_stems: set[str]
) -> int:
    if not overflow_directory.is_dir():
        return 0
    removed = 0
    for overflow_path in overflow_directory.glob("*.png"):
        if overflow_path.stem.lower() in migrated_stems:
            overflow_path.unlink()
            removed += 1
    try:
        overflow_directory.rmdir()
    except OSError:
        pass
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migra los artefactos del mapa web sin modificar Recursos"
    )
    parser.add_argument(
        "--resources", type=Path, default=PROJECT_ROOT.parent / "Recursos"
    )
    parser.add_argument("--workspace", type=Path, default=PROJECT_ROOT / "workspace")
    args = parser.parse_args()

    resources = args.resources.resolve()
    workspace = args.workspace.resolve()
    if resources == workspace or resources in workspace.parents:
        raise ValueError("workspace debe quedar fuera de Recursos")

    historical_assets = resources / "MiniMap"
    if (historical_assets / "minimapas").is_dir():
        source_minimaps = historical_assets / "minimapas"
        source_overflows = historical_assets / "desbordes"
    else:
        source_minimaps = workspace / "minimapas"
        source_overflows = workspace / "desbordes"

    minimaps, merged, migrated_stems = migrate_minimaps(
        source_minimaps, source_overflows, workspace / "minimapas")
    removed_overflows = remove_legacy_workspace_overflows(
        workspace / "desbordes", migrated_stems)
    database = resources / "map_content.sqlite"
    if not database.is_file():
        raise FileNotFoundError(database)
    shutil.copy2(database, workspace / "map_content.sqlite")
    print(f"workspace={workspace}")
    print(
        f"minimapas={minimaps} combinados_con_desborde={merged} "
        f"desbordes_obsoletos_eliminados={removed_overflows} database=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

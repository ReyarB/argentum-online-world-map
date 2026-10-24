"""Copia, sin borrar el origen, los artefactos web antiguos desde Recursos."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def copy_directory(source: Path, target: Path) -> int:
    if not source.is_dir():
        raise FileNotFoundError(source)
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in source.iterdir():
        if not path.is_file():
            continue
        shutil.copy2(path, target / path.name)
        copied += 1
    return copied


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

    minimaps = copy_directory(resources / "MiniMap" / "minimapas", workspace / "minimapas")
    overflows = copy_directory(resources / "MiniMap" / "desbordes", workspace / "desbordes")
    database = resources / "map_content.sqlite"
    if not database.is_file():
        raise FileNotFoundError(database)
    shutil.copy2(database, workspace / "map_content.sqlite")
    print(f"workspace={workspace}")
    print(f"minimapas={minimaps} desbordes={overflows} database=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

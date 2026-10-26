#!/usr/bin/env python3
"""
Mapa Mundo - migración VB6 a Python. Versión VB6-compatible 2026-05-28.

Requiere:
    pip install pillow

Uso normal:
    python mapa_mundo.py

El programa intenta autodetectar las carpetas. Si no encuentra los recursos,
pregunta las rutas con ventanas de selección y las guarda en mapa_mundo.ini
junto al script.

También se puede indicar manualmente:
    python mapa_mundo.py --base-dir C:/.../tools_ReyarB --data-file C:/.../Recursos/init/mapsworlddata.dat
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import sqlite3
import struct
import sys
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageTk
except ImportError as exc:
    raise SystemExit("Falta Pillow. Instalalo con: pip install pillow") from exc

TILE_SIZE = 27
EMPTY_TILE = 300
WATER_TILE = 400
APP_INI = "mapa_mundo.ini"
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 720


def application_dir() -> Path:
    """Devuelve la carpeta del script o del EXE empaquetado."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def hostile_npc_ids(npcs_path: Path) -> set[int]:
    """Lee la misma bandera Hostile que usa el servidor al cargar npcs.dat."""
    if not npcs_path.is_file():
        return set()
    result: set[int] = set()
    current_npc: Optional[int] = None
    with npcs_path.open("r", encoding="latin-1", errors="replace") as source:
        for raw_line in source:
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                current_npc = None
                if section.casefold().startswith("npc"):
                    try:
                        current_npc = int(section[3:])
                    except ValueError:
                        pass
                continue
            if current_npc is None or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().casefold() not in {"hostile", "hostil"}:
                continue
            try:
                if int(value.strip().split("'", 1)[0] or "0") != 0:
                    result.add(current_npc)
            except ValueError:
                continue
    return result


def quest_npc_ids(npcs_path: Path) -> set[int]:
    """Devuelve los NPC cuyo NpcType es Quest (17 en e_NPCType del servidor)."""
    if not npcs_path.is_file():
        return set()
    result: set[int] = set()
    current_npc: Optional[int] = None
    with npcs_path.open("r", encoding="latin-1", errors="replace") as source:
        for raw_line in source:
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                current_npc = None
                if section.casefold().startswith("npc"):
                    try:
                        current_npc = int(section[3:])
                    except ValueError:
                        pass
                continue
            if current_npc is None or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().casefold() != "npctype":
                continue
            try:
                if int(value.strip().split("'", 1)[0] or "0") == 17:
                    result.add(current_npc)
            except ValueError:
                continue
    return result


def tree_resource_kinds(obj_path: Path) -> Dict[int, str]:
    """Clasifica ObjType 4 igual que ModLumberjack: elfica, pino o comun."""
    if not obj_path.is_file():
        return {}
    sections: Dict[int, Dict[str, str]] = {}
    current_obj: Optional[int] = None
    with obj_path.open("r", encoding="latin-1", errors="replace") as source:
        for raw_line in source:
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                current_obj = None
                if section.casefold().startswith("obj"):
                    try:
                        current_obj = int(section[3:])
                        sections.setdefault(current_obj, {})
                    except ValueError:
                        pass
                continue
            if current_obj is None or "=" not in line:
                continue
            key, value = line.split("=", 1)
            sections[current_obj][key.strip().casefold()] = value.strip().split("'", 1)[0]

    result: Dict[int, str] = {}
    for obj_id, values in sections.items():
        if values.get("objtype") != "4":
            continue
        if values.get("elfico", "0") not in {"", "0"}:
            result[obj_id] = "elfica"
        elif values.get("pino", "0") not in {"", "0"}:
            result[obj_id] = "pino"
        else:
            result[obj_id] = "comun"
    return result


def indexed_sections(path: Path, prefix: str) -> Dict[int, Dict[str, str]]:
    """Lector tolerante para los DAT históricos con comentarios antes de [INIT]."""
    result: Dict[int, Dict[str, str]] = {}
    current: Optional[int] = None
    if not path.is_file():
        return result
    with path.open("r", encoding="latin-1", errors="replace") as source:
        for raw_line in source:
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                name = line[1:-1].strip()
                current = None
                if name.casefold().startswith(prefix.casefold()):
                    try:
                        current = int(name[len(prefix):])
                        result.setdefault(current, {})
                    except ValueError:
                        pass
                continue
            if current is None or "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[current][key.strip().casefold()] = value.strip()
    return result


def npc_information(npcs_path: Path, quests_path: Path) -> Tuple[Dict[int, str], Dict[int, List[Dict[str, int | str]]]]:
    npcs = indexed_sections(npcs_path, "NPC")
    quests = indexed_sections(quests_path, "QUEST")
    roles: Dict[int, str] = {}
    offers: Dict[int, List[Dict[str, int | str]]] = {}
    role_by_type = {
        1: "resucitador", 9: "resucitador",
        2: "guardia", 8: "guardia", 13: "guardia", 24: "guardia",
        3: "entrenador", 4: "banquero",
        10: "transporte", 26: "transporte",
    }
    for npc_id, values in npcs.items():
        try:
            npc_type = int(values.get("npctype", "0") or "0")
        except ValueError:
            npc_type = 0
        role = role_by_type.get(npc_type, "")
        if not role and values.get("comercia", "0") not in {"", "0"}:
            role = "comerciante"
        if role:
            roles[npc_id] = role
        try:
            count = int(values.get("numquest", "0") or "0")
        except ValueError:
            count = 0
        npc_offers: List[Dict[str, int | str]] = []
        for index in range(1, count + 1):
            try:
                quest_id = int(values.get(f"questnumber{index}", "0") or "0")
            except ValueError:
                continue
            quest = quests.get(quest_id, {})
            if quest_id <= 0:
                continue
            npc_offers.append({
                "id": quest_id,
                "name": quest.get("nombre", f"Quest {quest_id}"),
                "desc": quest.get("desc", ""),
                "level": quest.get("requiredlevel", "0"),
                "maxLevel": quest.get("limitlevel", "0"),
                "exp": quest.get("rewardexp", "0"),
                "gold": quest.get("rewardgld", "0"),
                "repeatable": quest.get("repetible", "0"),
            })
        if npc_offers:
            offers[npc_id] = npc_offers
    return roles, offers


def object_grh_indices(path: Path) -> Dict[int, int]:
    result: Dict[int, int] = {}
    for obj_id, values in indexed_sections(path, "OBJ").items():
        try:
            grh_index = int(values.get("grhindex", "0") or "0")
        except ValueError:
            continue
        if grh_index > 0:
            result[obj_id] = grh_index
    return result


def graphics_definitions(path: Path) -> Dict[int, List[int]]:
    result: Dict[int, List[int]] = {}
    if not path.is_file():
        return result
    with path.open("r", encoding="latin-1", errors="replace") as source:
        for raw_line in source:
            line = raw_line.strip().split("'", 1)[0]
            if not line.casefold().startswith("grh") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            try:
                grh_id = int(key[3:])
                values = [int(value) for value in raw_value.split("-") if value != ""]
            except ValueError:
                continue
            if values:
                result[grh_id] = values
    return result


def csm_map_metadata(path: Path) -> Dict[str, int | str]:
    """Lee los textos del encabezado CSM sin recorrer el contenido del mapa."""
    if not path.is_file():
        return {}
    try:
        data = path.read_bytes()
        if len(data) < 54:
            return {}
        signature = struct.unpack_from("<l", data, 0)[0]
        offset = (52 if signature == 0x324C3557 else 44) + 8

        def read_string(position: int) -> Tuple[str, int]:
            if position + 2 > len(data):
                raise ValueError("Cadena CSM truncada")
            length = struct.unpack_from("<H", data, position)[0]
            position += 2
            if position + length > len(data):
                raise ValueError("Cadena CSM fuera de rango")
            value = data[position:position + length].decode("cp1252", errors="replace")
            return value, position + length

        name, offset = read_string(offset)
        offset += 1  # backup_mode
        restrict_mode, offset = read_string(offset)
        offset += 8  # music_number_hi, music_number_low
        safe = data[offset]
        offset += 1
        zone, offset = read_string(offset)
        terrain, _offset = read_string(offset)
        return {
            "name": name.strip(), "restrict": restrict_mode.strip(),
            "zone": zone.strip(), "terrain": terrain.strip(),
            # En el CSM, Seguro=1 significa mapa no-PK.
            "pk": 0 if safe else 1,
        }
    except (OSError, ValueError, struct.error):
        return {}


def map_name_font_glyphs(base_dir: Path) -> Dict[str, List[int]]:
    """Devuelve los glifos de la fuente gráfica 8 usada al cambiar de mapa."""
    grhs = graphics_definitions(base_dir / "init" / "graficos.ini")
    character_grhs: Dict[str, int] = {}
    for code in range(ord("A"), ord("Z") + 1):
        character_grhs[chr(code)] = 27510 + code - ord("A")
    for code in range(ord("a"), ord("z") + 1):
        character_grhs[chr(code)] = 27536 + code - ord("a")
    for code in range(ord("0"), ord("9") + 1):
        character_grhs[chr(code)] = 27610 + code - ord("0")
    character_grhs.update({
        "Á": 27562, "É": 27563, "Í": 27564, "Ó": 27565, "Ú": 27566,
        "á": 27567, "é": 27568, "í": 27569, "ó": 27570, "ú": 27571,
        "Ñ": 27606, "ñ": 27607, "Ç": 27608, "ç": 27609,
        "¡": 27620, "!": 27621, "¿": 27622, "?": 27623,
        ".": 27624, ",": 27625, ";": 27626, ":": 27627,
        "-": 27655, "_": 27659, "(": 27632, ")": 27633,
        "'": 27641, '"': 27640, "/": 27646,
    })
    result: Dict[str, List[int]] = {}
    for character, grh_id in character_grhs.items():
        values = grhs.get(grh_id, [])
        if values and values[0] == 1 and len(values) >= 6:
            _frames, file_id, x, y, width, height = values[:6]
            if file_id == 19054 and width > 0 and height > 0:
                result[character] = [x, y, width, height]
    return result


def generate_object_icons(base_dir: Path, object_ids: set[int], target_dir: Path) -> Dict[int, str]:
    """Recorta el primer cuadro de cada GRH usado sin modificar los graficos fuente."""
    object_grhs = object_grh_indices(base_dir / "Dat" / "Obj.dat")
    grhs = graphics_definitions(base_dir / "init" / "graficos.ini")
    graphics_dir = base_dir / "Graficos"
    graphics_files = {
        path.stem.casefold(): path for path in graphics_dir.iterdir()
        if path.is_file() and path.suffix.casefold() in {".png", ".bmp"}
    } if graphics_dir.is_dir() else {}
    target_dir.mkdir(parents=True, exist_ok=True)

    def static_definition(grh_id: int) -> Optional[List[int]]:
        visited = set()
        while grh_id > 0 and grh_id not in visited:
            visited.add(grh_id)
            values = grhs.get(grh_id, [])
            if not values:
                return None
            if values[0] == 1 and len(values) >= 6:
                return values
            if values[0] > 1 and len(values) >= 2:
                grh_id = values[1]
                continue
            return None
        return None

    result: Dict[int, str] = {}
    opened_images: Dict[Path, Image.Image] = {}
    try:
        for obj_id in sorted(object_ids):
            definition = static_definition(object_grhs.get(obj_id, 0))
            if not definition:
                continue
            _frames, file_id, x, y, width, height = definition[:6]
            if width <= 0 or height <= 0:
                continue
            source_path = graphics_files.get(str(file_id).casefold())
            if source_path is None:
                continue
            try:
                source_image = opened_images.get(source_path)
                if source_image is None:
                    source_image = Image.open(source_path).convert("RGBA")
                    opened_images[source_path] = source_image
                if x < 0 or y < 0 or x + width > source_image.width or y + height > source_image.height:
                    continue
                icon = source_image.crop((x, y, x + width, y + height))
                if icon.getchannel("A").getbbox() is None:
                    continue
                icon_path = target_dir / f"Obj{obj_id}.png"
                icon.save(icon_path, format="PNG", optimize=True)
                result[obj_id] = f"iconos_obj/Obj{obj_id}.png"
            except (OSError, ValueError):
                continue
    finally:
        for source_image in opened_images.values():
            source_image.close()
    for stale_icon in target_dir.glob("Obj*.png"):
        try:
            stale_id = int(stale_icon.stem[3:])
        except ValueError:
            continue
        if stale_id not in result:
            stale_icon.unlink()
    return result


def generate_npc_icons(
    base_dir: Path, npc_ids: set[int], target_dir: Path
) -> Tuple[Dict[int, str], set[int]]:
    """Genera un icono por NPC desde su retrato o su primer cuadro frontal."""
    npcs = indexed_sections(base_dir / "Dat" / "npcs.dat", "NPC")
    bodies = indexed_sections(base_dir / "init" / "cuerpos.dat", "BODY")
    molds = indexed_sections(base_dir / "init" / "moldes.ini", "Molde")
    grhs = graphics_definitions(base_dir / "init" / "graficos.ini")
    graphics_dir = base_dir / "Graficos"
    graphics_files = {
        path.stem.casefold(): path for path in graphics_dir.iterdir()
        if path.is_file() and path.suffix.casefold() in {".png", ".bmp"}
    } if graphics_dir.is_dir() else {}
    target_dir.mkdir(parents=True, exist_ok=True)

    def integer(values: Dict[str, str], key: str) -> int:
        try:
            return int(values.get(key, "0").split("'", 1)[0].strip() or "0")
        except ValueError:
            return 0

    def static_definition(grh_id: int) -> Optional[List[int]]:
        visited = set()
        while grh_id > 0 and grh_id not in visited:
            visited.add(grh_id)
            values = grhs.get(grh_id, [])
            if not values:
                return None
            if values[0] == 1 and len(values) >= 6:
                return values[:6]
            if values[0] > 1 and len(values) >= 2:
                grh_id = values[1]
                continue
            return None
        return None

    def body_definition(body_id: int) -> Optional[List[int]]:
        body = bodies.get(body_id, {})
        for key in ("walk3", "walk1", "walk2", "walk4"):
            definition = static_definition(integer(body, key))
            if definition:
                return definition
        mold = molds.get(integer(body, "std"), {})
        file_id = integer(body, "filenum")
        if not mold or file_id <= 0:
            return None
        x, y = integer(mold, "x"), integer(mold, "y")
        width, height = integer(mold, "width"), integer(mold, "height")
        if width <= 0 or height <= 0 or integer(mold, "dir1") <= 0:
            return None
        return [1, file_id, x, y, width, height]

    result: Dict[int, str] = {}
    face_icons: set[int] = set()
    opened_images: Dict[Path, Image.Image] = {}
    try:
        for npc_id in sorted(npc_ids):
            npc = npcs.get(npc_id, {})
            definition = static_definition(integer(npc, "npcfacegrh"))
            uses_face = definition is not None
            if not definition:
                definition = body_definition(integer(npc, "body"))
            if not definition:
                continue
            _frames, file_id, x, y, width, height = definition
            source_path = graphics_files.get(str(file_id).casefold())
            if source_path is None or width <= 0 or height <= 0:
                continue
            try:
                source_image = opened_images.get(source_path)
                if source_image is None:
                    source_image = Image.open(source_path).convert("RGBA")
                    opened_images[source_path] = source_image
                if x < 0 or y < 0 or x + width > source_image.width or y + height > source_image.height:
                    continue
                icon = source_image.crop((x, y, x + width, y + height))
                if icon.getchannel("A").getbbox() is None:
                    continue
                icon_path = target_dir / f"Npc{npc_id}.png"
                icon.save(icon_path, format="PNG", optimize=True)
                result[npc_id] = f"iconos_npc/Npc{npc_id}.png"
                if uses_face:
                    face_icons.add(npc_id)
            except (OSError, ValueError):
                continue
    finally:
        for source_image in opened_images.values():
            source_image.close()
    for stale_icon in target_dir.glob("Npc*.png"):
        try:
            stale_id = int(stale_icon.stem[3:])
        except ValueError:
            continue
        if stale_id not in result:
            stale_icon.unlink()
    return result, face_icons


@dataclass
class PathsConfig:
    base_dir: Path
    data_file: Path
    render_dir: Path
    export_dir: Path
    web_output_dir: Path
    database_file: Optional[Path] = None
    interface_dir: Optional[Path] = None


class AppPaths:
    def __init__(self, script_dir: Path):
        self.script_dir = script_dir.resolve()
        self.ini_path = self.script_dir / APP_INI
        self.config = configparser.ConfigParser()
        if self.ini_path.exists():
            self.config.read(self.ini_path, encoding="utf-8")

    def get_path(self, key: str) -> Optional[Path]:
        value = self.config.get("paths", key, fallback="").strip()
        if not value:
            return None
        return Path(value).expanduser().resolve()

    def set_paths(self, paths: PathsConfig) -> None:
        if not self.config.has_section("paths"):
            self.config.add_section("paths")
        self.config["paths"]["base_dir"] = str(paths.base_dir)
        self.config["paths"]["data_file"] = str(paths.data_file)
        self.config["paths"]["render_dir"] = str(paths.render_dir)
        self.config["paths"]["export_dir"] = str(paths.export_dir)
        self.config["paths"]["web_output_dir"] = str(paths.web_output_dir)
        self.config["paths"]["database_file"] = str(paths.database_file or "")
        self.config["paths"]["interface_dir"] = str(paths.interface_dir or "")
        with self.ini_path.open("w", encoding="utf-8") as f:
            self.config.write(f)

    def resolve(
        self,
        cli_base: Optional[Path],
        cli_data_file: Optional[Path],
        cli_web_output: Optional[Path] = None,
        cli_database: Optional[Path] = None,
    ) -> PathsConfig:
        base_dir = (cli_base or self.get_path("base_dir") or self.script_dir).resolve()
        data_file = (cli_data_file or self.get_path("data_file") or self._find_data_file(base_dir))
        render_dir = self.get_path("render_dir") or self._find_render_dir(base_dir)
        export_dir = self.get_path("export_dir") or (base_dir / "exportacion")
        web_output_dir = (
            cli_web_output or self.get_path("web_output_dir") or self.script_dir.parent / "dist-web"
        )
        database_file = (
            cli_database or self.get_path("database_file") or base_dir / "map_content.sqlite"
        )
        interface_dir = self.get_path("interface_dir") or self._find_interface_dir(base_dir)
        if interface_dir and interface_dir.name.lower() == "interface":
            interface_dir = interface_dir.parent / "ui" / "maps"

        missing: List[str] = []
        if not data_file or not data_file.exists():
            missing.append("mapsworlddata.dat")
        elif not is_valid_world_data_file(data_file):
            missing.append("mapsworlddata.dat válido (formato VB6: [INIT]/TOTALWORLDS y [WORLDMAP#]/ANCHO/ALTO)")
        if not render_dir or not render_dir.is_dir():
            missing.append("carpeta render con mapa<ID>.bmp")

        if missing:
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "Faltan rutas o archivo inválido",
                "No se encontraron estos recursos:\n\n- " + "\n- ".join(missing) +
                "\n\nTe voy a pedir las rutas y las guardaré en mapa_mundo.ini."
            )
            while not data_file or not data_file.exists() or not is_valid_world_data_file(data_file):
                chosen = filedialog.askopenfilename(
                    title="Seleccioná mapsworlddata.dat válido",
                    filetypes=[("World data", "mapsworlddata.dat"), ("DAT", "*.dat"), ("Todos", "*.*")],
                    initialdir=str(base_dir),
                )
                if not chosen:
                    raise SystemExit("No se seleccionó un mapsworlddata.dat válido.")
                data_file = Path(chosen).resolve()
                if not is_valid_world_data_file(data_file):
                    messagebox.showerror(
                        "Archivo inválido",
                        f"Este archivo no parece ser un mapsworlddata.dat válido:\n\n{data_file}\n\nDebe tener formato VB6: [INIT] con TOTALWORLDS y [WORLDMAP#] con ANCHO/ALTO. Se lee sin distinguir mayúsculas/minúsculas."
                    )
            if not render_dir or not render_dir.is_dir():
                chosen = filedialog.askdirectory(
                    title="Seleccioná la carpeta render que contiene mapa<ID>.bmp",
                    initialdir=str(base_dir),
                )
                if not chosen:
                    raise SystemExit("No se seleccionó la carpeta render.")
                render_dir = Path(chosen).resolve()
            root.destroy()

        # Ajustar base_dir al padre de render si el usuario eligió .../render.
        if render_dir and render_dir.name.lower() == "render":
            base_dir = render_dir.parent.resolve()
        export_dir = export_dir.resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        web_output_dir = web_output_dir.resolve()
        web_output_dir.mkdir(parents=True, exist_ok=True)
        database_file = database_file.resolve()

        paths = PathsConfig(
            base_dir=base_dir,
            data_file=data_file.resolve(),
            render_dir=render_dir.resolve(),
            export_dir=export_dir,
            web_output_dir=web_output_dir,
            database_file=database_file if database_file.is_file() else None,
            interface_dir=interface_dir.resolve() if interface_dir else None,
        )
        self.set_paths(paths)
        return paths

    def _candidate_roots(self, base_dir: Path) -> List[Path]:
        roots = [base_dir.resolve(), self.script_dir]
        roots.extend(base_dir.resolve().parents)
        roots.extend(self.script_dir.parents)
        unique: List[Path] = []
        for p in roots:
            if p not in unique:
                unique.append(p)
        return unique

    def _find_data_file(self, base_dir: Path) -> Optional[Path]:
        candidates: List[Path] = []
        for root in self._candidate_roots(base_dir):
            candidates.extend([
                root / "init" / "mapsworlddata.dat",
                root / "Recursos" / "init" / "mapsworlddata.dat",
                root.parent / "Recursos" / "init" / "mapsworlddata.dat",
            ])
        for p in candidates:
            if p.exists():
                return p.resolve()
        return None

    def _find_render_dir(self, base_dir: Path) -> Optional[Path]:
        candidates: List[Path] = []
        for root in self._candidate_roots(base_dir):
            candidates.extend([root / "render", root / "tools_ReyarB" / "render"])
        for p in candidates:
            if p.is_dir():
                # Preferir carpetas que realmente tengan BMPs.
                if any(p.glob("mapa*.bmp")) or any(p.glob("*.bmp")):
                    return p.resolve()
        for p in candidates:
            if p.is_dir():
                return p.resolve()
        return None

    def _find_interface_dir(self, base_dir: Path) -> Optional[Path]:
        for root in self._candidate_roots(base_dir):
            for p in [root / "ui" / "maps", root / "Recursos" / "ui" / "maps", root.parent / "Recursos" / "ui" / "maps"]:
                if p.is_dir():
                    return p.resolve()
        return None



def _section_items_ci(cfg: configparser.ConfigParser, section: str) -> Dict[str, str]:
    """Devuelve las claves de una sección en mayúsculas para leer sin depender del casing."""
    return {str(k).upper(): str(v) for k, v in cfg[section].items()}


def _world_section_number(section: str) -> int:
    name = section.upper()
    if name.startswith("WORLDMAP"):
        tail = name.replace("WORLDMAP", "", 1)
        if tail.isdigit():
            return int(tail)
    return 10**9


def _world_sections(cfg: configparser.ConfigParser) -> List[str]:
    sections = [s for s in cfg.sections() if s.upper().startswith("WORLDMAP")]
    return sorted(sections, key=_world_section_number)


def _get_int_ci(cfg: configparser.ConfigParser, section: str, key: str, fallback: int = 0) -> int:
    try:
        data = _section_items_ci(cfg, section)
        value = data.get(key.upper())
        if value is None or str(value).strip() == "":
            return fallback
        return int(str(value).strip())
    except Exception:
        return fallback


def _set_preserving_key_case(cfg: configparser.ConfigParser, section: str, key: str, value: int | str) -> None:
    """Actualiza una clave usando el mismo casing si ya existe; si no, usa el casing pedido."""
    wanted = key.upper()
    real_key = None
    if cfg.has_section(section):
        for existing in cfg[section].keys():
            if str(existing).upper() == wanted:
                real_key = existing
                break
    cfg[section][real_key or key] = str(value)


def _get_section_ci(cfg: configparser.ConfigParser, section_name: str) -> Optional[str]:
    """Busca una sección sin distinguir mayúsculas/minúsculas."""
    wanted = section_name.upper()
    for sec in cfg.sections():
        if sec.upper() == wanted:
            return sec
    return None


def _read_total_worlds_vb6(cfg: configparser.ConfigParser) -> int:
    """Replica el VB6: Val(Leer.GetValue("INIT", "TotalWorlds")), pero case-insensitive."""
    init_sec = _get_section_ci(cfg, "INIT")
    if not init_sec:
        return 0
    return _get_int_ci(cfg, init_sec, "TOTALWORLDS", 0)


def _world_sections_vb6(cfg: configparser.ConfigParser, total: int) -> List[str]:
    """Devuelve WORLDMAP1..WORLDMAP{TotalWorlds}, como hace el VB6."""
    out: List[str] = []
    for n in range(1, total + 1):
        sec = _get_section_ci(cfg, f"WORLDMAP{n}")
        if sec:
            out.append(sec)
    return out


def is_valid_world_data_file(path: Path) -> bool:
    """
    Valida el mapsworlddata.dat del VB6 sin cambiar su formato.

    El VB6 usa:
      GetValue("INIT", "TotalWorlds")
      GetValue("WORLDMAP" & j, "Alto")
      GetValue("WORLDMAP" & j, "Ancho")

    clsIniManager no distingue mayúsculas/minúsculas, por eso acá aceptamos
    TOTALWORLDS/TotalWorlds y ANCHO/Ancho/ALTO/Alto.
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
        cfg = configparser.ConfigParser(strict=False)
        cfg.optionxform = str
        with path.open("r", encoding="cp1252", errors="replace") as f:
            cfg.read_file(f)

        total = _read_total_worlds_vb6(cfg)
        if total <= 0:
            return False

        sections = _world_sections_vb6(cfg, total)
        if len(sections) < total:
            return False

        for sec in sections:
            ancho = _get_int_ci(cfg, sec, "ANCHO", 0)
            alto = _get_int_ci(cfg, sec, "ALTO", 0)
            if ancho <= 0 or alto <= 0:
                return False
        return True
    except Exception:
        return False


@dataclass
class WorldMap:
    ancho: int
    alto: int
    map_indices: List[int] = field(default_factory=list)


class WorldData:
    def __init__(self, path: Path):
        self.path = path
        self.worlds: List[WorldMap] = []
        self.config = configparser.ConfigParser(strict=False)
        self.config.optionxform = str

    def load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"No existe el archivo de mundos: {self.path}")
        with self.path.open("r", encoding="cp1252", errors="replace") as f:
            self.config.read_file(f)

        total = _read_total_worlds_vb6(self.config)
        if total <= 0:
            raise ValueError(
                f"{self.path} no tiene [INIT]/TOTALWORLDS válido. "
                "El lector es case-insensitive, pero la clave debe existir."
            )

        self.worlds.clear()
        for n in range(1, total + 1):
            sec = _get_section_ci(self.config, f"WORLDMAP{n}")
            if not sec:
                raise ValueError(f"Falta la sección [WORLDMAP{n}] en {self.path}")

            ancho = _get_int_ci(self.config, sec, "ANCHO", 0)
            alto = _get_int_ci(self.config, sec, "ALTO", 0)
            if ancho <= 0 or alto <= 0:
                raise ValueError(f"La sección [{sec}] no tiene ANCHO/ALTO válidos")

            # Igual que VB6: i = 1 To Alto * Ancho
            indices = [_get_int_ci(self.config, sec, str(i), 0) for i in range(1, ancho * alto + 1)]
            self.worlds.append(WorldMap(ancho=ancho, alto=alto, map_indices=indices))

    def save(self) -> None:
        # Guardado compatible con VB6: mantiene [INIT]/TOTALWORLDS y [WORLDMAP#].
        # No cambia el casing existente si el archivo ya tenía TOTALWORLDS, ANCHO, ALTO, etc.
        init_sec = _get_section_ci(self.config, "INIT")
        if not init_sec:
            self.config.add_section("INIT")
            init_sec = "INIT"
        _set_preserving_key_case(self.config, init_sec, "TOTALWORLDS", len(self.worlds))

        for n, world in enumerate(self.worlds, start=1):
            sec = _get_section_ci(self.config, f"WORLDMAP{n}") or f"WORLDMAP{n}"
            if not self.config.has_section(sec):
                self.config.add_section(sec)
            _set_preserving_key_case(self.config, sec, "ANCHO", world.ancho)
            _set_preserving_key_case(self.config, sec, "ALTO", world.alto)
            for i, value in enumerate(world.map_indices, start=1):
                _set_preserving_key_case(self.config, sec, str(i), value)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="cp1252", newline="\r\n") as f:
            self.config.write(f, space_around_delimiters=False)


class MapaMundoApp(tk.Tk):
    def __init__(self, paths: PathsConfig):
        super().__init__()
        self.title("Renderizador de mundo por Ladder - Python VB6-compatible")
        screen_x = max((self.winfo_screenwidth() - WINDOW_WIDTH) // 2, 0)
        screen_y = max((self.winfo_screenheight() - WINDOW_HEIGHT) // 2, 0)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{screen_x}+{screen_y}")
        self.resizable(False, False)

        self.paths = paths
        self.base_dir = paths.base_dir
        self.render_dir = paths.render_dir
        self.export_dir = paths.export_dir
        self.web_output_dir = paths.web_output_dir
        self.database_file = paths.database_file
        self.interface_dir = paths.interface_dir
        self.data_file = paths.data_file

        self.data = WorldData(self.data_file)
        self.data.load()
        if not self.data.worlds:
            messagebox.showerror(
                "WorldData vacío",
                f"El archivo no contiene mundos para cargar:\n\n{self.data_file}\n\nBorrá mapa_mundo.ini o ejecutá con --reset-config para elegir otro archivo."
            )
            raise SystemExit("El archivo no contiene mundos para cargar. Usá --reset-config para elegir otro mapsworlddata.dat.")

        self.selected_world = 0
        self.changed = False
        self.translating = False
        self.temp_tile: Optional[int] = None
        self.temp_index: Optional[int] = None
        self.current_image: Optional[Image.Image] = None
        self.current_photo: Optional[ImageTk.PhotoImage] = None
        self.image_offset_x = 0
        self.image_offset_y = 0
        self.missing_tiles: set[int] = set()
        self.alternative_tiles: set[int] = set()

        self._build_ui()
        self._select_world(0)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        top = tk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        tk.Label(top, text="Mundo:").pack(side=tk.LEFT)
        self.world_var = tk.StringVar(value="1")
        self.world_menu = tk.OptionMenu(top, self.world_var, *[str(i) for i in range(1, len(self.data.worlds) + 1)], command=self._world_changed)
        self.world_menu.pack(side=tk.LEFT, padx=(4, 12))

        self.size_label = tk.Label(top, text="")
        self.size_label.pack(side=tk.LEFT, padx=(0, 12))

        self.empty_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Vacío", variable=self.empty_var).pack(side=tk.LEFT)
        self.water_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Agua", variable=self.water_var).pack(side=tk.LEFT)
        self.translate_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Transladar", variable=self.translate_var).pack(side=tk.LEFT)

        tk.Button(top, text="Guardar mundos", command=self.save_world).pack(side=tk.RIGHT, padx=4)

        self.status = tk.Label(self, text="", anchor="w")
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=3)

        canvas_frame = tk.Frame(self)
        canvas_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._canvas_click)
        self.canvas.bind("<Button-3>", self._canvas_click)
        self.canvas.bind("<Configure>", self._canvas_resized)

    def _world_changed(self, value: str) -> None:
        self._select_world(int(value) - 1)

    def _select_world(self, index: int) -> None:
        self.selected_world = index
        world = self.world
        self.size_label.config(text=f"Ancho: {world.ancho}  Alto: {world.alto}")
        self.render_current()

    @property
    def world(self) -> WorldMap:
        return self.data.worlds[self.selected_world]

    def _folder_for_tile_size(self, folder: str) -> Optional[Path]:
        if folder == "render":
            return self.render_dir
        p = self.base_dir / folder
        return p if p.is_dir() else None

    def _tile_directories(self, folder: str) -> List[Path]:
        primary = self._folder_for_tile_size(folder)
        candidates = [primary] if primary else []
        if folder == "render":
            candidates.extend([
                self.base_dir / "Render",
                self.base_dir / "tools_ReyarB" / "render",
            ])
        result: List[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).casefold()
            if candidate.is_dir() and key not in seen:
                result.append(candidate)
                seen.add(key)
        return result

    @staticmethod
    def _uniform_image(image: Image.Image) -> bool:
        return all(low == high for low, high in image.getextrema())

    def render_world(self, world: WorldMap, tile_size: int, folder: str) -> Image.Image:
        out = Image.new("RGB", (world.ancho * tile_size, world.alto * tile_size), "black")
        tile_directories = self._tile_directories(folder)
        cache: Dict[int, Image.Image] = {}
        for idx, tile_id in enumerate(world.map_indices):
            x = (idx % world.ancho) * tile_size
            y = (idx // world.ancho) * tile_size
            tile = cache.get(tile_id)
            if tile is None:
                available_tiles: List[Tuple[int, Path, Image.Image, bool]] = []
                for tile_directory in tile_directories:
                    tile_path = tile_directory / f"mapa{tile_id}.bmp"
                    if not tile_path.exists():
                        continue
                    with Image.open(tile_path) as source:
                        candidate = source.convert("RGB")
                    available_tiles.append((
                        tile_path.stat().st_mtime_ns,
                        tile_directory,
                        candidate,
                        self._uniform_image(candidate),
                    ))
                selected_directory: Optional[Path] = None
                usable_tiles = [entry for entry in available_tiles if not entry[3]]
                if usable_tiles:
                    _, selected_directory, tile, _ = max(usable_tiles, key=lambda entry: entry[0])
                elif available_tiles:
                    _, selected_directory, tile, _ = max(available_tiles, key=lambda entry: entry[0])
                if tile is None:
                    self.missing_tiles.add(tile_id)
                    tile = Image.new("RGB", (tile_size, tile_size), "black")
                else:
                    if selected_directory != tile_directories[0]:
                        self.alternative_tiles.add(tile_id)
                    if tile.size != (tile_size, tile_size):
                        tile = tile.resize((tile_size, tile_size), Image.Resampling.NEAREST)
                cache[tile_id] = tile
            out.paste(tile, (x, y))
        return out

    def render_current(self) -> None:
        self.missing_tiles.clear()
        self.alternative_tiles.clear()
        self.current_image = self.render_world(self.world, TILE_SIZE, "render")
        self.current_photo = ImageTk.PhotoImage(self.current_image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.current_photo, anchor="nw", tags="world-image")
        self._center_current_image()
        msg = f"Mundo N: {self.selected_world + 1} | DAT: {self.data_file} | render: {self.render_dir}"
        if self.missing_tiles:
            sample = ", ".join(map(str, sorted(self.missing_tiles)[:8]))
            msg += f" | Faltan BMP: {sample}"
        if self.alternative_tiles:
            sample = ", ".join(map(str, sorted(self.alternative_tiles)[:8]))
            msg += f" | Respaldo válido: {sample}"
        self._set_status(msg)

    def _canvas_resized(self, _event: tk.Event) -> None:
        self._center_current_image()

    def _center_current_image(self) -> None:
        if self.current_image is None:
            return
        canvas_width = max(self.canvas.winfo_width(), 1)
        canvas_height = max(self.canvas.winfo_height(), 1)
        self.image_offset_x = max((canvas_width - self.current_image.width) // 2, 0)
        self.image_offset_y = max((canvas_height - self.current_image.height) // 2, 0)
        self.canvas.coords("world-image", self.image_offset_x, self.image_offset_y)
        content_width = max(canvas_width, self.image_offset_x + self.current_image.width)
        content_height = max(canvas_height, self.image_offset_y + self.current_image.height)
        self.canvas.config(scrollregion=(0, 0, content_width, content_height))

    def write_world_index(self) -> Path:
        if not self.data.worlds:
            raise ValueError("No hay WORLDMAP1 para generar MiniMap/index.htm")
        world = self.data.worlds[0]
        minimap_root = self.web_output_dir
        minimap_root.mkdir(parents=True, exist_ok=True)
        target = minimap_root / "index.htm"
        database_path = self.database_file
        placed_map_ids = {
            map_id for map_id in world.map_indices
            if map_id > 0 and map_id != EMPTY_TILE
        }
        layer_definitions = [
            ("wood", "Madera común", "#2cff72", "object"),
            ("pine", "Madera de pino", "#9ade4b", "object"),
            ("elven", "Madera élfica", "#bd7cff", "object"),
            ("iron", "Hierro", "#aeb7c2", "object"),
            ("silver", "Plata", "#e8edf4", "object"),
            ("gold", "Oro", "#ffd43b", "object"),
            ("coal", "Carbón", "#60656b", "object"),
            ("blodium", "Blodium", "#e04cff", "object"),
            ("otherOre", "Otros yacimientos", "#ffad3b", "object"),
            ("npc", "Otros NPCs", "#35cfff", "npc"),
            ("merchant", "Comerciantes", "#4ed6b4", "npc"),
            ("banker", "Banqueros", "#48a8ff", "npc"),
            ("trainer", "Entrenadores", "#8fd35f", "npc"),
            ("resurrector", "Resucitadores", "#d29cff", "npc"),
            ("transport", "Transporte", "#47d6e8", "npc"),
            ("guard", "Guardias", "#8aa5ff", "npc"),
            ("hostile", "NPCs hostiles", "#ff4242", "npc"),
            ("quest", "NPCs de quest", "#ffd43b", "quest"),
            ("portal", "Portales", "#ff71cf", "object"),
            ("poi", "Puntos de interés", "#ffffff", "object"),
        ]
        layer_maps: Dict[str, Dict[int, List[Dict[str, int | str]]]] = {
            layer_id: {} for layer_id, _label, _color, _kind in layer_definitions
        }
        map_info: Dict[int, Dict[str, int | str]] = {}
        map_connections: Dict[int, set[int]] = {}
        npcs_path = self.base_dir / "Dat" / "npcs.dat"
        hostile_ids = hostile_npc_ids(npcs_path)
        quest_ids = quest_npc_ids(npcs_path)
        npc_definitions = indexed_sections(npcs_path, "NPC")
        npc_roles, npc_offers = npc_information(npcs_path, self.base_dir / "Dat" / "Quests.DAT")
        object_definitions = indexed_sections(self.base_dir / "Dat" / "Obj.dat", "OBJ")
        tree_kinds = tree_resource_kinds(self.base_dir / "Dat" / "Obj.dat")

        def resource_object_id(obj_id: int, obj_type: int) -> int:
            values = object_definitions.get(obj_id, {})
            if obj_type == 4:
                if values.get("elfico", "0") not in {"", "0"}:
                    return 2781  # Leña élfica
                if values.get("pino", "0") not in {"", "0"}:
                    return 3788  # Pino nudoso
                return 58  # Leña común
            if obj_type == 22:
                try:
                    return int(values.get("mineralindex", "0") or "0") or obj_id
                except ValueError:
                    return obj_id
            return obj_id

        def append_point(layer_id: str, map_id: int, point: Dict[str, int | str]) -> None:
            layer_maps[layer_id].setdefault(map_id, []).append(point)

        def mineral_layer(name: str) -> str:
            folded = name.casefold()
            if "hierro" in folded:
                return "iron"
            if "plata" in folded:
                return "silver"
            if "oro" in folded:
                return "gold"
            if "carb" in folded:
                return "coal"
            if "blodium" in folded:
                return "blodium"
            return "otherOre"

        if database_path and database_path.is_file():
            connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
            try:
                map_rows = connection.execute(
                    "SELECT map_id, file_name, file_path, COALESCE(map_name,''), "
                    "COALESCE(terrain,''), COALESCE(zone,''), COALESCE(pk,0), "
                    "COALESCE(restrict_mode,'') FROM maps"
                ).fetchall()
                directory_counts: Dict[str, int] = {}
                for row in map_rows:
                    directory = str(Path(str(row[2])).parent).casefold()
                    directory_counts[directory] = directory_counts.get(directory, 0) + 1
                active_directory = max(directory_counts, key=directory_counts.get) if directory_counts else ""
                active_files = {
                    (int(row[0]), str(row[1])) for row in map_rows
                    if str(Path(str(row[2])).parent).casefold() == active_directory
                }
                for map_id, file_name, file_path, name, terrain, zone, pk, restrict_mode in map_rows:
                    if (int(map_id), str(file_name)) not in active_files or int(map_id) not in placed_map_ids:
                        continue
                    map_info[int(map_id)] = {
                        "name": str(name), "terrain": str(terrain), "zone": str(zone),
                        "pk": int(pk), "restrict": str(restrict_mode),
                    }

                rows = connection.execute(
                    "SELECT map_id,file_name,x,y,obj_id,obj_type,COALESCE(obj_name,'') "
                    "FROM map_objects WHERE obj_type IN (4,8,19,22,27,28) "
                    "ORDER BY map_id,y,x,obj_id,file_name"
                )
                seen_objects = set()
                for map_id, file_name, x, y, obj_id, obj_type, obj_name in rows:
                    map_id, x, y, obj_id, obj_type = map(int, (map_id, x, y, obj_id, obj_type))
                    if (map_id, str(file_name)) not in active_files or map_id not in placed_map_ids:
                        continue
                    if not (14 <= x <= 87 and 11 <= y <= 90):
                        continue
                    if obj_type in {4, 22}:
                        try:
                            resource_capacity = int(
                                object_definitions.get(obj_id, {}).get("vidautil", "0") or "0"
                            )
                        except ValueError:
                            resource_capacity = 0
                        # Al cargar el mapa, el servidor reemplaza amount por
                        # ObjData(...).VidaUtil. Con VidaUtil=0 es decorativo.
                        if resource_capacity <= 0:
                            continue
                    key = (map_id, x, y, obj_id)
                    if key in seen_objects:
                        continue
                    seen_objects.add(key)
                    official_obj_name = object_definitions.get(obj_id, {}).get("name", "").strip()
                    display_obj_name = official_obj_name or str(obj_name)
                    point: Dict[str, int | str] = {
                        "x": x, "y": y, "obj": obj_id, "name": display_obj_name,
                    }
                    if obj_type == 4:
                        resource_id = resource_object_id(obj_id, obj_type)
                        point["iconObj"] = resource_id
                        point["resourceName"] = object_definitions.get(resource_id, {}).get("name", "")
                        tree_kind = tree_kinds.get(obj_id, "comun")
                        append_point({"elfica": "elven", "pino": "pine"}.get(tree_kind, "wood"), map_id, point)
                    elif obj_type == 22:
                        resource_id = resource_object_id(obj_id, obj_type)
                        point["iconObj"] = resource_id
                        point["resourceName"] = object_definitions.get(resource_id, {}).get("name", "")
                        append_point(mineral_layer(display_obj_name), map_id, point)
                    elif obj_type == 19:
                        append_point("portal", map_id, point)
                    else:
                        append_point("poi", map_id, point)

                npc_rows = connection.execute(
                    "SELECT map_id,file_name,x,y,npc_id,COALESCE(npc_name,'') "
                    "FROM map_npcs ORDER BY map_id,y,x,npc_id,file_name"
                )
                seen_npcs = set()
                role_layers = {
                    "comerciante": "merchant", "banquero": "banker", "entrenador": "trainer",
                    "resucitador": "resurrector", "transporte": "transport", "guardia": "guard",
                }
                for map_id, file_name, x, y, npc_id, npc_name in npc_rows:
                    map_id, x, y, npc_id = map(int, (map_id, x, y, npc_id))
                    if (map_id, str(file_name)) not in active_files or map_id not in placed_map_ids:
                        continue
                    if not (14 <= x <= 87 and 11 <= y <= 90):
                        continue
                    key = (map_id, x, y, npc_id)
                    if key in seen_npcs:
                        continue
                    seen_npcs.add(key)
                    official_name = npc_definitions.get(npc_id, {}).get("name", "").strip()
                    point = {
                        "x": x, "y": y, "npc": npc_id,
                        "name": official_name or str(npc_name),
                    }
                    if npc_id in quest_ids:
                        layer_id = "quest"
                    elif npc_id in hostile_ids:
                        layer_id = "hostile"
                    else:
                        layer_id = role_layers.get(npc_roles.get(npc_id, ""), "npc")
                    append_point(layer_id, map_id, point)

                exit_rows = connection.execute(
                    "SELECT map_id,file_name,to_map FROM map_exits WHERE COALESCE(to_map,0)>0"
                )
                for map_id, file_name, to_map in exit_rows:
                    map_id, to_map = int(map_id), int(to_map)
                    if (map_id, str(file_name)) in active_files and map_id in placed_map_ids and to_map != map_id:
                        map_connections.setdefault(map_id, set()).add(to_map)
            finally:
                connection.close()

        # Los CSM son la fuente oficial de estos textos y conservan su
        # codificación; la base auxiliar puede contener caracteres reemplazados.
        for map_id in placed_map_ids:
            metadata = csm_map_metadata(self.base_dir / "Mapas" / f"mapa{map_id}.csm")
            if not metadata:
                continue
            info = map_info.setdefault(map_id, {"pk": 0})
            for key, value in metadata.items():
                if key == "pk" or value:
                    info[key] = value

        # Una etiqueta por componente contiguo de mapas con el mismo nombre.
        # Así una ciudad o un mar de varios mapas no repite el texto por casilla.
        grid = [
            world.map_indices[row * world.ancho:(row + 1) * world.ancho]
            for row in range(world.alto)
        ]
        visited_cells: set[Tuple[int, int]] = set()
        area_labels: List[Dict[str, int | float | str]] = []
        for row in range(world.alto):
            for col in range(world.ancho):
                if (col, row) in visited_cells:
                    continue
                map_id = grid[row][col]
                name = str(map_info.get(map_id, {}).get("name", "")).strip()
                if not name or name.casefold() == "libre":
                    visited_cells.add((col, row))
                    continue
                folded_name = name.casefold()
                component: List[Tuple[int, int]] = []
                pending = [(col, row)]
                visited_cells.add((col, row))
                while pending:
                    current_col, current_row = pending.pop()
                    component.append((current_col, current_row))
                    for next_col, next_row in (
                        (current_col - 1, current_row), (current_col + 1, current_row),
                        (current_col, current_row - 1), (current_col, current_row + 1),
                    ):
                        if not (0 <= next_col < world.ancho and 0 <= next_row < world.alto):
                            continue
                        if (next_col, next_row) in visited_cells:
                            continue
                        next_id = grid[next_row][next_col]
                        next_name = str(map_info.get(next_id, {}).get("name", "")).strip()
                        if next_name.casefold() != folded_name:
                            continue
                        visited_cells.add((next_col, next_row))
                        pending.append((next_col, next_row))
                area_labels.append({
                    "name": name,
                    "zone": str(map_info.get(map_id, {}).get("zone", "")).strip(),
                    "col": sum(cell[0] + 0.5 for cell in component) / len(component),
                    "row": sum(cell[1] + 0.5 for cell in component) / len(component),
                    "count": len(component),
                })

        layers = []
        for layer_id, label, color, kind in layer_definitions:
            points_by_map = {
                map_id: points for map_id, points in layer_maps[layer_id].items()
                if map_id in placed_map_ids
            }
            layers.append({
                "id": layer_id, "label": label, "color": color, "kind": kind,
                "total": sum(len(points) for points in points_by_map.values()), "maps": points_by_map,
            })
        connections = {map_id: sorted(destinations) for map_id, destinations in map_connections.items()}
        used_object_ids = {
            int(point.get("iconObj", point["obj"]))
            for layer in layers if layer["kind"] == "object"
            for points in layer["maps"].values()
            for point in points if int(point.get("obj", 0)) > 0
        }
        object_icons = generate_object_icons(
            self.base_dir, used_object_ids, minimap_root / "iconos_obj"
        )
        used_npc_ids = {
            int(point["npc"])
            for layer in layers if layer["kind"] in {"npc", "quest"}
            for points in layer["maps"].values()
            for point in points if int(point.get("npc", 0)) > 0
        }
        npc_icons, npc_face_icons = generate_npc_icons(
            self.base_dir, used_npc_ids, minimap_root / "iconos_npc"
        )
        search_items: List[Dict[str, int | str]] = []
        for map_id in sorted(placed_map_ids):
            info = map_info.get(map_id, {})
            search_items.append({
                "map": map_id, "type": "Mapa",
                "label": f"Mapa {map_id} - {info.get('name', '')} {info.get('zone', '')}".strip(),
            })
        seen_search = set()
        for layer in layers:
            for map_id, points in layer["maps"].items():
                for point in points:
                    name = str(point.get("resourceName", point.get("name", ""))).strip()
                    identity = point.get("npc", point.get("obj", ""))
                    label = f"{layer['label']}: {name or identity}"
                    key = (map_id, label)
                    if key not in seen_search:
                        seen_search.add(key)
                        search_items.append({"map": map_id, "type": layer["label"], "label": label})
                    if layer["id"] == "quest":
                        for quest in npc_offers.get(int(point.get("npc", 0)), []):
                            quest_label = f"Quest {quest['id']}: {quest['name']}"
                            quest_key = (map_id, quest_label)
                            if quest_key not in seen_search:
                                seen_search.add(quest_key)
                                search_items.append({"map": map_id, "type": "Quest", "label": quest_label})

        embedded_layers = json.dumps(layers, ensure_ascii=True, separators=(",", ":"))
        embedded_map_info = json.dumps(map_info, ensure_ascii=True, separators=(",", ":"))
        embedded_connections = json.dumps(connections, ensure_ascii=True, separators=(",", ":"))
        embedded_offers = json.dumps(npc_offers, ensure_ascii=True, separators=(",", ":"))
        embedded_search = json.dumps(search_items, ensure_ascii=True, separators=(",", ":"))
        embedded_object_icons = json.dumps(object_icons, ensure_ascii=True, separators=(",", ":"))
        embedded_npc_icons = json.dumps(npc_icons, ensure_ascii=True, separators=(",", ":"))
        embedded_npc_face_icons = json.dumps(
            sorted(npc_face_icons), ensure_ascii=True, separators=(",", ":")
        )
        embedded_area_labels = json.dumps(area_labels, ensure_ascii=True, separators=(",", ":"))
        embedded_map_font = json.dumps(
            map_name_font_glyphs(self.base_dir), ensure_ascii=True, separators=(",", ":")
        )
        lines = [
            '<!doctype html>',
            '<html lang="es">',
            "<head>",
            "<title>Mapa mundo</title>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            "<style>",
            "@font-face{font-family:'Alegreya Sans AO';src:url('assets/fonts/Alegreya%20Sans%20AO.ttf') format('truetype');font-display:swap}",
            "html,body{width:100%;height:100%;margin:0;overflow:hidden;background:#111;color:#eee;font:14px Segoe UI,Arial,sans-serif}",
            "#toolbar{position:fixed;z-index:20;left:12px;top:12px;display:flex;flex-direction:column;align-items:stretch;gap:7px;box-sizing:border-box;max-height:calc(117.647vh - 28.235px);padding:8px 10px;background:#202428ee;border:1px solid #555;border-radius:7px;box-shadow:0 2px 12px #0008;transform:scale(.85);transform-origin:top left}",
            "#toolbar button{min-width:34px;height:30px;background:#343a40;color:#eee;border:1px solid #687078;border-radius:4px;cursor:pointer}",
            "#toolbar button:hover{background:#454d55}",
            ".panel-toggle{width:34px;padding:0;font-size:17px;line-height:28px}",
            "#toolbar.collapsed #layers,#toolbar.collapsed #search-results{display:none}",
            "#zoomLabel{min-width:48px;text-align:center}",
            "#zoom-controls{display:flex;align-items:center;gap:8px}",
            "#search{width:285px;box-sizing:border-box;padding:6px 8px;background:#11171b;color:#eee;border:1px solid #687078;border-radius:4px}",
            "#search-results{display:none;max-height:210px;overflow:auto;background:#151a1e;border:1px solid #596068;border-radius:4px}",
            ".search-result{display:block;width:100%;height:auto!important;text-align:left;padding:6px!important;border:0!important;border-bottom:1px solid #343a40!important;border-radius:0!important}",
            "#layers{display:flex;min-height:0;flex-direction:column;align-items:flex-start;gap:5px;padding-top:7px;border-top:1px solid #596068;overflow:auto}",
            "#layers label{display:block;white-space:nowrap}",
            ".layer-title{margin-top:4px;color:#9fa8b0;text-transform:uppercase;font-size:11px}",
            "#viewport{position:absolute;inset:0;overflow:hidden;cursor:grab;user-select:none}",
            "#viewport.dragging{cursor:grabbing}",
            "#mapCanvas{position:absolute;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}",
            "#world{position:absolute;z-index:1;left:0;top:0;display:grid;gap:0;transform-origin:0 0}",
            ".map-cell{position:relative;width:592px;height:640px;overflow:visible}",
            ".map-cell>img{display:block;width:592px;height:640px;visibility:hidden;pointer-events:none}",
            ".map-counts{position:absolute;z-index:3;right:9px;top:9px;display:flex;flex-direction:column;align-items:center;gap:5px;pointer-events:none}",
            ".map-count{display:none;width:34px;height:34px;align-items:center;justify-content:center;border-radius:50%;color:#fff;font-size:17px;font-weight:700;text-shadow:0 1px 2px #000;box-shadow:0 2px 5px #0008;border:1px solid #ffffff44}",
            "body.counts-on .map-count.layer-active{display:flex}",
            ".selected{outline:4px solid #49a8ff;outline-offset:-4px}",
            "#details{position:fixed;z-index:20;right:12px;top:12px;width:300px;min-width:220px;min-height:120px;max-width:calc(117.647vw - 28.235px);max-height:calc(117.647vh - 28.235px);overflow:auto;resize:both;padding:10px 12px;background:#202428ee;border:1px solid #555;border-radius:7px;box-shadow:0 2px 12px #0008;display:none;transform:scale(.85);transform-origin:top right}",
            "#detailsHeader{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:30px}",
            "#details.collapsed{width:300px;height:auto;min-width:220px;min-height:0;overflow:hidden;resize:none}",
            "#details.collapsed #detailsExpanded{display:none}",
            "#details.collapsed #detailsSummary{padding-bottom:8px;border-bottom:1px solid #c8c8c8}",
            "#details strong{color:#71d99b}",
            "#help{position:fixed;z-index:20;left:12px;bottom:10px;padding:6px 9px;background:#202428dd;border-radius:5px;color:#bbb;transform:scale(.85);transform-origin:bottom left}",
            "#markerTooltip{position:fixed;z-index:40;display:none;max-width:320px;padding:9px 11px;background:#171d21f2;color:#eee;border:1px solid #77818a;border-radius:6px;box-shadow:0 3px 14px #000b;pointer-events:none;line-height:1.35;transform:scale(.75);transform-origin:top left}",
            "#markerTooltip strong{display:block;margin-bottom:3px;color:#f5e7b0;font-size:15px}",
            "#settingsBackdrop{position:fixed;z-index:60;inset:0;display:none;align-items:center;justify-content:center;background:#0009}",
            "#settingsBackdrop.open{display:flex}",
            "#settingsPanel{width:min(520px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;box-sizing:border-box;padding:18px 20px;background:#20272c;color:#eee;border:1px solid #77818a;border-radius:9px;box-shadow:0 8px 35px #000d}",
            "#settingsPanel h2{margin:0 0 5px;color:#f5e7b0}",
            "#settingsPanel .settings-help{margin:0 0 15px;color:#aeb7bf}",
            ".setting-row{display:grid;grid-template-columns:170px 1fr 64px;align-items:center;gap:10px;margin:12px 0}",
            ".setting-row input[type=range]{width:100%}",
            ".setting-row output{text-align:right;color:#f5e7b0;font-weight:600}",
            ".setting-row select{grid-column:2/4;padding:6px;background:#11171b;color:#eee;border:1px solid #687078;border-radius:4px}",
            ".settings-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:18px;padding-top:13px;border-top:1px solid #596068}",
            ".settings-actions button{padding:7px 12px;background:#343a40;color:#eee;border:1px solid #687078;border-radius:4px;cursor:pointer}",
            ".settings-actions button:hover{background:#454d55}",
            "</style>",
            "</head>",
            "<body>",
            '<div id="toolbar">',
            '  <div id="zoom-controls">',
            '  <button id="zoomOut" title="Alejar">-</button>',
            '  <span id="zoomLabel">100%</span>',
            '  <button id="zoomIn" title="Acercar">+</button>',
            '  <button id="fit" title="Ver el mundo completo">Ajustar</button>',
            '  <button id="actual" title="Tamano original de los BMP">100%</button>',
            '  <button id="toggleToolbar" class="panel-toggle" title="Reducir controles" aria-label="Reducir controles">&#9650;</button>',
            '  </div>',
            '  <input id="search" type="text" autocomplete="new-password" autocorrect="off" autocapitalize="off" spellcheck="false" placeholder="Buscar mapa, NPC, quest o recurso...">',
            '  <div id="search-results"></div>',
            '  <div id="layers">',
            f'  <label><input id="showAreaNames" type="checkbox" checked> '
            f'Nombres de áreas ({len(area_labels)})</label>',
            '  <label><input id="showCounts" type="checkbox"> Contadores por mapa</label>',
        ]
        groups = [(0, "Recursos"), (9, "NPCs"), (18, "Mundo")]
        group_titles = {index: title for index, title in groups}
        for index, layer in enumerate(layers):
            if index in group_titles:
                lines.append(f'  <span class="layer-title">{group_titles[index]}</span>')
            lines.append(
                f'  <label><input id="layer-{layer["id"]}" type="checkbox"> '
                f'{layer["label"]} ({layer["total"]})</label>'
            )
        lines.extend(['  </div>', '</div>', '<div id="viewport"><canvas id="mapCanvas"></canvas><div id="world">'])
        for row in range(world.alto):
            start = row * world.ancho
            for tile_id in world.map_indices[start:start + world.ancho]:
                lines.append(f'  <div class="map-cell" data-map="{tile_id}" title="Mapa {tile_id}">')
                lines.append(f'    <img class="base-map" data-src="minimapas/Mapa{tile_id}.webp" alt="Mapa {tile_id}" draggable="false">')
                lines.append(f'    <img class="overflow-map" data-src="desbordes/Mapa{tile_id}.png" alt="" draggable="false">')
                counts = [
                    (layer["id"], layer["label"], layer["color"], len(layer["maps"].get(tile_id, [])))
                    for layer in layers if layer["maps"].get(tile_id)
                ]
                if counts:
                    lines.append('    <div class="map-counts">')
                    for layer_id, label, color, count in counts:
                        lines.append(
                            f'      <span class="map-count" data-layer="{layer_id}" '
                            f'style="background:{color}" title="{label}: {count}">{count}</span>'
                        )
                    lines.append('    </div>')
                lines.append('  </div>')
        lines.extend([
            "</div></div>",
            '<aside id="details"><div id="detailsHeader"><b id="detailsTitle"></b><button id="toggleDetails" class="panel-toggle" title="Reducir información" aria-label="Reducir información">&#9650;</button></div><div id="detailsContent"></div></aside>',
            '<div id="help">Rueda: zoom &nbsp; | &nbsp; Arrastrar: mover &nbsp; | &nbsp; Doble clic: ver detalles</div>',
            '<div id="markerTooltip" role="tooltip"></div>',
            '<div id="settingsBackdrop" aria-hidden="true">',
            '  <section id="settingsPanel" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">',
            '    <h2 id="settingsTitle">Configuración del mapa</h2>',
            '    <p class="settings-help">Los valores están limitados a rangos seguros. F1 abre o cierra este menú.</p>',
            '    <div class="setting-row"><label for="settingFace">Tamaño de caras</label><input id="settingFace" type="range" min="5" max="40" step="1"><output id="settingFaceValue"></output></div>',
            '    <div class="setting-row"><label for="settingBody">Tamaño de cuerpos</label><input id="settingBody" type="range" min="30" max="120" step="5"><output id="settingBodyValue"></output></div>',
            '    <div class="setting-row"><label for="settingObject">Recursos y objetos</label><input id="settingObject" type="range" min="40" max="160" step="5"><output id="settingObjectValue"></output></div>',
            '    <div class="setting-row"><label for="settingAreaSize">Nombres de áreas</label><input id="settingAreaSize" type="range" min="50" max="350" step="10"><output id="settingAreaSizeValue"></output></div>',
            '    <div class="setting-row"><label for="settingTooltip">Espera de información</label><input id="settingTooltip" type="range" min="300" max="3000" step="100"><output id="settingTooltipValue"></output></div>',
            '    <div class="setting-row"><label for="settingFont">Fuente de áreas</label><select id="settingFont"><option value="game">Fuente gráfica del juego</option><option value="alegreya">Alegreya Sans AO</option><option value="segoe">Segoe UI</option></select></div>',
            '    <div class="settings-actions"><button id="resetSettings">Restaurar predeterminados</button><button id="saveSettings">Guardar y cerrar</button></div>',
            '  </section>',
            '</div>',
            "<script>",
            f"const LAYERS={embedded_layers};",
            f"const MAP_INFO={embedded_map_info};",
            f"const CONNECTIONS={embedded_connections};",
            f"const NPC_QUESTS={embedded_offers};",
            f"const SEARCH_ITEMS={embedded_search};",
            f"const OBJ_ICONS={embedded_object_icons};",
            f"const NPC_ICONS={embedded_npc_icons};",
            f"const NPC_FACE_ICONS=new Set({embedded_npc_face_icons});",
            f"const AREA_LABELS={embedded_area_labels};",
            f"const MAP_FONT={embedded_map_font};",
            f"const COLS={world.ancho}, ROWS={world.alto}, TILE_W=592, TILE_H=640;",
            "const DEFAULT_SETTINGS=Object.freeze({faceScale:15,bodyScale:70,objectScale:100,areaScale:260,tooltipDelay:1000,areaFont:'game'}),SETTING_LIMITS={faceScale:[5,40],bodyScale:[30,120],objectScale:[40,160],areaScale:[50,350],tooltipDelay:[300,3000]},SETTINGS_KEY='mapaMundoSettingsV3';",
            "function validatedSettings(raw){const value={...DEFAULT_SETTINGS};Object.entries(SETTING_LIMITS).forEach(([key,range])=>{const number=Number(raw&&raw[key]);if(Number.isFinite(number))value[key]=Math.min(range[1],Math.max(range[0],number));});if(['game','alegreya','segoe'].includes(raw&&raw.areaFont))value.areaFont=raw.areaFont;return value;}",
            "function loadSettings(){try{return validatedSettings(JSON.parse(localStorage.getItem(SETTINGS_KEY)||'{}'));}catch(_error){return {...DEFAULT_SETTINGS};}}",
            "let SETTINGS=loadSettings();",
            "const viewport=document.getElementById('viewport'),world=document.getElementById('world'),mapCanvas=document.getElementById('mapCanvas'),mapContext=mapCanvas.getContext('2d'),zoomLabel=document.getElementById('zoomLabel'),toolbar=document.getElementById('toolbar'),details=document.getElementById('details'),detailsTitle=document.getElementById('detailsTitle'),detailsContent=document.getElementById('detailsContent'),markerTooltip=document.getElementById('markerTooltip'),settingsBackdrop=document.getElementById('settingsBackdrop');",
            "const OBJ_IMAGES={};Object.entries(OBJ_ICONS).forEach(([id,source])=>{const image=new Image();image.onload=scheduleRender;image.onerror=scheduleRender;image.src=source;OBJ_IMAGES[id]=image;});",
            "const NPC_IMAGES={};Object.entries(NPC_ICONS).forEach(([id,source])=>{const image=new Image();image.onload=scheduleRender;image.onerror=scheduleRender;image.src=source;NPC_IMAGES[id]=image;});",
            "const MAP_FONT_IMAGE=new Image(),AREA_LABEL_CACHE={};MAP_FONT_IMAGE.onload=scheduleRender;MAP_FONT_IMAGE.onerror=scheduleRender;MAP_FONT_IMAGE.src='assets/graphics/19054.png';",
            "world.style.gridTemplateColumns=`repeat(${COLS},${TILE_W}px)`;",
            "let scale=1,panX=0,panY=0,dragging=false,moved=false,startX=0,startY=0,startPanX=0,startPanY=0,renderPending=false,mapCells=[],hoverTimer=0,hoverKey='';const VISIBLE_MARKERS=[];",
            "function separateFaceMarker(x,y,width,height,occupied){const gap=Math.max(1,2*scale),originBottom=y+4*scale,makeBox=(cx,bottom)=>({left:cx-width/2-gap,right:cx+width/2+gap,top:bottom-height-gap,bottom:bottom+gap,cx,bottom}),overlaps=box=>occupied.some(other=>box.left<other.right&&box.right>other.left&&box.top<other.bottom&&box.bottom>other.top);let box=makeBox(x,originBottom);if(!overlaps(box)){occupied.push(box);return box;}const nudge=Math.max(4*scale,Math.min(width,height)*.16);for(let attempt=1;attempt<=24;attempt++){const ring=Math.ceil(attempt/8),angle=((attempt-1)%8)*Math.PI/4,distance=nudge*ring,cx=x+Math.cos(angle)*distance,bottom=originBottom+Math.sin(angle)*distance;if(!occupied.some(other=>Math.hypot(cx-other.cx,bottom-other.bottom)<nudge*.7)){box=makeBox(cx,bottom);occupied.push(box);return box;}}occupied.push(box);return box;}",
            "function drawMarkerSet(points,col,row,mapId,layer,occupiedFaces){if(!points)return;mapContext.fillStyle=layer.color;mapContext.strokeStyle='#071015';mapContext.lineWidth=Math.max(1,1.25*scale);const radius=Math.max(1.5,4.5*scale);points.forEach(p=>{const x=panX+(col*TILE_W+(p.x-14+.5)*8)*scale,y=panY+(row*TILE_H+(p.y-11+.5)*8)*scale,img=layer.kind==='object'?OBJ_IMAGES[p.iconObj||p.obj]:NPC_IMAGES[p.npc],key=`${mapId}:${layer.id}:${p.x}:${p.y}:${p.npc||p.obj||''}`;if(img&&img.complete&&img.naturalWidth&&scale>=.12){const usesFace=layer.kind!=='object'&&NPC_FACE_ICONS.has(Number(p.npc)),layerScale=(layer.kind==='object'?SETTINGS.objectScale:(usesFace?SETTINGS.faceScale:SETTINGS.bodyScale))/100;let width=img.naturalWidth*scale*layerScale,height=img.naturalHeight*scale*layerScale;const maximum=192*scale,largest=Math.max(width,height);if(largest>maximum){const factor=maximum/largest;width*=factor;height*=factor;}const position=usesFace?separateFaceMarker(x,y,width,height,occupiedFaces):{cx:x,bottom:y+4*scale};mapContext.save();mapContext.shadowColor='#000c';mapContext.shadowBlur=Math.max(1,2*scale);mapContext.drawImage(img,position.cx-width/2,position.bottom-height,width,height);mapContext.restore();VISIBLE_MARKERS.push({key,mapId,layer,point:p,left:position.cx-width/2,top:position.bottom-height,right:position.cx+width/2,bottom:position.bottom});}else{mapContext.beginPath();mapContext.arc(x,y,radius,0,Math.PI*2);mapContext.fill();mapContext.stroke();const hitRadius=Math.max(6,radius);VISIBLE_MARKERS.push({key,mapId,layer,point:p,left:x-hitRadius,top:y-hitRadius,right:x+hitRadius,bottom:y+hitRadius});}});}",
            "function areaLabelBitmap(text){if(AREA_LABEL_CACHE[text])return AREA_LABEL_CACHE[text];if(!MAP_FONT_IMAGE.complete||!MAP_FONT_IMAGE.naturalWidth)return null;const glyphs=Array.from(text).map(character=>character===' '?null:(MAP_FONT[character]||MAP_FONT['?']));const width=Math.max(1,glyphs.reduce((total,glyph)=>total+(glyph?glyph[2]:12),0)),canvas=document.createElement('canvas'),context=canvas.getContext('2d');canvas.width=width;canvas.height=64;let x=0;glyphs.forEach(glyph=>{if(glyph){context.drawImage(MAP_FONT_IMAGE,glyph[0],glyph[1],glyph[2],glyph[3],x,0,glyph[2],glyph[3]);x+=glyph[2];}else{x+=12;}});context.globalCompositeOperation='source-in';context.fillStyle='#f5e7b0';context.fillRect(0,0,width,64);AREA_LABEL_CACHE[text]=canvas;return canvas;}",
            "function drawAreaLabels(){if(!document.getElementById('showAreaNames').checked)return;const w=viewport.clientWidth,h=viewport.clientHeight,fontSize=Math.max(7,Math.min(55,30*Math.sqrt(scale)*SETTINGS.areaScale/100)),occupied=[],gameFont=SETTINGS.areaFont==='game',fontFamily=SETTINGS.areaFont==='alegreya'?\"'Alegreya Sans AO',serif\":\"'Segoe UI',Arial,sans-serif\",candidates=AREA_LABELS.filter(label=>scale>=.18||label.count>=(scale<.1?3:2)||String(label.zone).toUpperCase()==='CIUDAD').sort((a,b)=>{const cityA=String(a.zone).toUpperCase()==='CIUDAD'?1:0,cityB=String(b.zone).toUpperCase()==='CIUDAD'?1:0;return cityB-cityA||b.count-a.count||a.name.localeCompare(b.name);});mapContext.save();if(!gameFont){mapContext.font=`700 ${fontSize}px ${fontFamily}`;mapContext.textAlign='center';mapContext.textBaseline='middle';mapContext.lineJoin='round';mapContext.lineWidth=Math.max(3,fontSize*.16);mapContext.strokeStyle='#10120fe8';mapContext.fillStyle='#f5e7b0';}candidates.forEach(label=>{const bitmap=gameFont?areaLabelBitmap(label.name):null;if(gameFont&&!bitmap)return;const x=panX+label.col*TILE_W*scale,y=panY+label.row*TILE_H*scale;if(x<-180||y<-60||x>w+180||y>h+60)return;const maxWidth=Math.max(90,Math.sqrt(label.count)*TILE_W*scale*1.15),naturalWidth=gameFont?bitmap.width*fontSize/64:mapContext.measureText(label.name).width,textWidth=Math.min(naturalWidth,maxWidth),textHeight=fontSize,padding=fontSize*.45,box={left:x-textWidth/2-padding,right:x+textWidth/2+padding,top:y-textHeight/2-padding,bottom:y+textHeight/2+padding};if(occupied.some(other=>box.left<other.right&&box.right>other.left&&box.top<other.bottom&&box.bottom>other.top))return;occupied.push(box);if(gameFont){mapContext.save();mapContext.shadowColor='#10120f';mapContext.shadowBlur=Math.max(3,fontSize*.2);mapContext.shadowOffsetX=Math.max(1,fontSize*.04);mapContext.shadowOffsetY=Math.max(1,fontSize*.04);mapContext.drawImage(bitmap,x-textWidth/2,y-textHeight/2,textWidth,textHeight);mapContext.restore();}else{mapContext.strokeText(label.name,x,y,maxWidth);mapContext.fillText(label.name,x,y,maxWidth);}});mapContext.restore();}",
            "function drawVisibleMarkers(){const active=LAYERS.filter(layer=>document.getElementById('layer-'+layer.id).checked);if(!active.length)return;const w=viewport.clientWidth,h=viewport.clientHeight,occupiedFaces=[];for(let index=0;index<mapCells.length;index++){const col=index%COLS,row=Math.floor(index/COLS),x0=panX+col*TILE_W*scale,y0=panY+row*TILE_H*scale,x1=x0+TILE_W*scale,y1=y0+TILE_H*scale;if(x1<0||y1<0||x0>w||y0>h)continue;const id=Number(mapCells[index].dataset.map);active.forEach(layer=>drawMarkerSet(layer.maps[id],col,row,id,layer,occupiedFaces));}}",
            "function ensureImage(image){if(!image.src&&image.dataset.src)image.src=image.dataset.src;}",
            "function renderVisible(){renderPending=false;VISIBLE_MARKERS.length=0;const dpr=window.devicePixelRatio||1,w=viewport.clientWidth,h=viewport.clientHeight;if(mapCanvas.width!==Math.round(w*dpr)||mapCanvas.height!==Math.round(h*dpr)){mapCanvas.width=Math.round(w*dpr);mapCanvas.height=Math.round(h*dpr);}mapContext.setTransform(dpr,0,0,dpr,0,0);mapContext.clearRect(0,0,w,h);for(let index=0;index<mapCells.length;index++){const col=index%COLS,row=Math.floor(index/COLS),x0=Math.floor(panX+col*TILE_W*scale),y0=Math.floor(panY+row*TILE_H*scale),x1=Math.ceil(panX+(col+1)*TILE_W*scale),y1=Math.ceil(panY+(row+1)*TILE_H*scale);if(x1<0||y1<0||x0>w||y0>h)continue;const image=mapCells[index].querySelector('.base-map');ensureImage(image);if(image.complete&&image.naturalWidth)mapContext.drawImage(image,x0,y0,x1-x0,y1-y0);}for(let index=0;index<mapCells.length;index++){const image=mapCells[index].querySelector('.overflow-map'),col=index%COLS,row=Math.floor(index/COLS),estimatedX=panX+col*TILE_W*scale,estimatedY=panY+row*TILE_H*scale;if(estimatedX+TILE_W*scale<0||estimatedY+TILE_H*scale<0||estimatedX>w||estimatedY>h)continue;ensureImage(image);if(!image.complete||!image.naturalWidth)continue;const paddingX=(image.naturalWidth-TILE_W)/2,paddingY=(image.naturalHeight-TILE_H)/2,x0=Math.floor(panX+(col*TILE_W-paddingX)*scale),y0=Math.floor(panY+(row*TILE_H-paddingY)*scale),x1=Math.ceil(x0+image.naturalWidth*scale),y1=Math.ceil(y0+image.naturalHeight*scale);if(x1<0||y1<0||x0>w||y0>h)continue;mapContext.drawImage(image,x0,y0,x1-x0,y1-y0);}drawAreaLabels();drawVisibleMarkers();}",
            "function scheduleRender(){if(renderPending)return;renderPending=true;requestAnimationFrame(renderVisible);}",
            "function apply(){world.style.transform=`translate(${panX}px,${panY}px) scale(${scale})`;zoomLabel.textContent=`${Math.round(scale*100)}%`;scheduleRender();}",
            "function clampScale(v){return Math.min(2,Math.max(0.025,v));}",
            "function zoomAt(clientX,clientY,next){next=clampScale(next);const rect=viewport.getBoundingClientRect();const x=clientX-rect.left,y=clientY-rect.top;const wx=(x-panX)/scale,wy=(y-panY)/scale;scale=next;panX=x-wx*scale;panY=y-wy*scale;apply();}",
            "function centerAtScale(next){scale=clampScale(next);panX=(viewport.clientWidth-COLS*TILE_W*scale)/2;panY=(viewport.clientHeight-ROWS*TILE_H*scale)/2;apply();}",
            "function fit(){const pad=28;centerAtScale(Math.min((viewport.clientWidth-pad*2)/(COLS*TILE_W),(viewport.clientHeight-pad*2)/(ROWS*TILE_H)));}",
            "viewport.addEventListener('wheel',e=>{e.preventDefault();zoomAt(e.clientX,e.clientY,scale*(e.deltaY<0?1.15:1/1.15));},{passive:false});",
            "viewport.addEventListener('pointerdown',e=>{if(e.button!==0)return;dragging=true;moved=false;startX=e.clientX;startY=e.clientY;startPanX=panX;startPanY=panY;viewport.setPointerCapture(e.pointerId);viewport.classList.add('dragging');});",
            "viewport.addEventListener('pointermove',e=>{if(!dragging)return;const dx=e.clientX-startX,dy=e.clientY-startY;if(Math.abs(dx)+Math.abs(dy)>4)moved=true;panX=startPanX+dx;panY=startPanY+dy;apply();});",
            "viewport.addEventListener('pointerup',e=>{dragging=false;viewport.classList.remove('dragging');viewport.releasePointerCapture(e.pointerId);});",
            "document.getElementById('zoomIn').onclick=()=>zoomAt(innerWidth/2,innerHeight/2,scale*1.25);",
            "document.getElementById('zoomOut').onclick=()=>zoomAt(innerWidth/2,innerHeight/2,scale/1.25);",
            "document.getElementById('fit').onclick=fit;",
            "document.getElementById('actual').onclick=()=>zoomAt(innerWidth/2,innerHeight/2,1);",
            "function togglePanel(panel,button,expandedLabel,collapsedLabel){const collapsed=panel.classList.toggle('collapsed');button.textContent=collapsed?'\\u25bc':'\\u25b2';button.title=button.ariaLabel=collapsed?collapsedLabel:expandedLabel;}",
            "document.getElementById('toggleToolbar').onclick=()=>togglePanel(toolbar,document.getElementById('toggleToolbar'),'Reducir controles','Desplegar controles');",
            "document.getElementById('toggleDetails').onclick=()=>togglePanel(details,document.getElementById('toggleDetails'),'Reducir información','Desplegar información');",
            "function updateCountVisibility(){document.body.classList.toggle('counts-on',document.getElementById('showCounts').checked);document.querySelectorAll('.map-count').forEach(badge=>badge.classList.toggle('layer-active',document.getElementById('layer-'+badge.dataset.layer).checked));}",
            "document.getElementById('showCounts').onchange=updateCountVisibility;LAYERS.forEach(layer=>document.getElementById('layer-'+layer.id).onchange=()=>{updateCountVisibility();scheduleRender();});",
            "document.getElementById('showAreaNames').onchange=scheduleRender;",
            "const SETTING_INPUTS={faceScale:document.getElementById('settingFace'),bodyScale:document.getElementById('settingBody'),objectScale:document.getElementById('settingObject'),areaScale:document.getElementById('settingAreaSize'),tooltipDelay:document.getElementById('settingTooltip')},SETTING_OUTPUTS={faceScale:document.getElementById('settingFaceValue'),bodyScale:document.getElementById('settingBodyValue'),objectScale:document.getElementById('settingObjectValue'),areaScale:document.getElementById('settingAreaSizeValue'),tooltipDelay:document.getElementById('settingTooltipValue')},settingFont=document.getElementById('settingFont');",
            "function syncSettingsControls(){Object.entries(SETTING_INPUTS).forEach(([key,input])=>{input.value=SETTINGS[key];SETTING_OUTPUTS[key].textContent=key==='tooltipDelay'?`${(SETTINGS[key]/1000).toFixed(1)} s`:`${Math.round(SETTINGS[key])}%`;});settingFont.value=SETTINGS.areaFont;}",
            "function applySettingsControls(){const raw={areaFont:settingFont.value};Object.entries(SETTING_INPUTS).forEach(([key,input])=>raw[key]=Number(input.value));SETTINGS=validatedSettings(raw);syncSettingsControls();hideMarkerTooltip();scheduleRender();}",
            "function saveCurrentSettings(){try{localStorage.setItem(SETTINGS_KEY,JSON.stringify(SETTINGS));}catch(_error){/* El archivo local puede bloquear almacenamiento. */}}",
            "function openSettings(){syncSettingsControls();settingsBackdrop.classList.add('open');settingsBackdrop.setAttribute('aria-hidden','false');document.getElementById('settingFace').focus();}",
            "function closeSettings(save=true){if(save)saveCurrentSettings();settingsBackdrop.classList.remove('open');settingsBackdrop.setAttribute('aria-hidden','true');}",
            "Object.values(SETTING_INPUTS).forEach(input=>input.addEventListener('input',applySettingsControls));settingFont.addEventListener('change',()=>{applySettingsControls();if(document.fonts&&SETTINGS.areaFont==='alegreya')document.fonts.load(\"700 24px 'Alegreya Sans AO'\").then(scheduleRender);});",
            "document.getElementById('resetSettings').onclick=()=>{SETTINGS={...DEFAULT_SETTINGS};syncSettingsControls();saveCurrentSettings();hideMarkerTooltip();scheduleRender();};document.getElementById('saveSettings').onclick=()=>closeSettings(true);settingsBackdrop.addEventListener('pointerdown',event=>{if(event.target===settingsBackdrop)closeSettings(true);});syncSettingsControls();",
            "function escapeHtml(value){return String(value).replace(/[&<>\"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[ch]));}",
            "function markerTooltipHtml(hit){const p=hit.point,layer=hit.layer,isObject=layer.kind==='object',identity=isObject?`Objeto ${p.obj||''}`:`NPC ${p.npc||''}`,title=p.name||p.resourceName||identity,lines=[`${escapeHtml(layer.label)} · Mapa ${hit.mapId}`,`X ${p.x}, Y ${p.y}${identity?' · '+escapeHtml(identity):''}`];if(p.resourceName)lines.push(`Recurso: ${escapeHtml(p.resourceName)}`);if(layer.kind==='quest'){const quests=NPC_QUESTS[p.npc]||[];if(quests.length)lines.push(`Quests: ${quests.map(q=>escapeHtml(q.name)).join(', ')}`);}return `<strong>${escapeHtml(title)}</strong>${lines.join('<br>')}`;}",
            "function hideMarkerTooltip(){clearTimeout(hoverTimer);hoverTimer=0;hoverKey='';markerTooltip.style.display='none';}",
            "function markerAt(x,y){for(let index=VISIBLE_MARKERS.length-1;index>=0;index--){const marker=VISIBLE_MARKERS[index];if(x>=marker.left&&x<=marker.right&&y>=marker.top&&y<=marker.bottom)return marker;}return null;}",
            "viewport.addEventListener('pointermove',event=>{if(dragging){hideMarkerTooltip();return;}const hit=markerAt(event.clientX,event.clientY);if(!hit){hideMarkerTooltip();return;}if(hit.key===hoverKey)return;clearTimeout(hoverTimer);markerTooltip.style.display='none';hoverKey=hit.key;const left=Math.min(event.clientX+14,Math.max(8,innerWidth-255)),top=Math.min(event.clientY+14,Math.max(8,innerHeight-120));hoverTimer=setTimeout(()=>{if(hoverKey!==hit.key)return;markerTooltip.innerHTML=markerTooltipHtml(hit);markerTooltip.style.left=`${left}px`;markerTooltip.style.top=`${top}px`;markerTooltip.style.display='block';},SETTINGS.tooltipDelay);});",
            "viewport.addEventListener('pointerleave',hideMarkerTooltip);viewport.addEventListener('pointerdown',hideMarkerTooltip);viewport.addEventListener('wheel',hideMarkerTooltip,{passive:true});",
            "function layerDetails(layer,id){const points=layer.maps[id]||[];if(!points.length)return '';const rows=points.slice(0,80).map(p=>{let text;if(layer.kind==='object'&&p.iconObj){text=`X ${p.x}, Y ${p.y}: - ${escapeHtml(p.name||('Objeto '+p.obj))}`;if(p.resourceName)text+=` - Recurso: ${escapeHtml(p.resourceName)}`;}else{const identity=layer.kind==='object'?'obj. '+p.obj:'NPC '+p.npc;text=`X ${p.x}, Y ${p.y}: ${identity}${p.name?' - '+escapeHtml(p.name):''}`;}if(layer.kind==='quest'){const offers=NPC_QUESTS[p.npc]||[];offers.forEach(q=>{text+=`<div style=\"margin:4px 0 5px 12px;color:#ddd\"><b>Quest ${q.id}: ${escapeHtml(q.name)}</b><br>${escapeHtml(q.desc)}<br>Nivel ${q.level}${String(q.maxLevel)!=='0'?' a '+q.maxLevel:''} · EXP ${q.exp} · Oro ${q.gold}${String(q.repeatable)!=='0'?' · Repetible':''}</div>`;});}return text;}).join('<br>');return `<strong style=\"color:${layer.color}\">${escapeHtml(layer.label)}: ${points.length}</strong><br>${rows}${points.length>80?'<br>... y '+(points.length-80)+' más':''}`;}",
            "function showMapDetails(cell){const id=Number(cell.dataset.map),info=MAP_INFO[id]||{},exits=CONNECTIONS[id]||[];document.querySelectorAll('.selected').forEach(n=>n.classList.remove('selected'));cell.classList.add('selected');details.style.display='block';detailsTitle.textContent=`Mapa ${id}${info.name?' - '+info.name:''}`;const unsafe=Number(info.pk)!==0,safety=`<strong style=\"color:${unsafe?'#ff6565':'#71d99b'}\">${unsafe?'Mapa inseguro':'Mapa seguro'}</strong>`,status=`Zona: ${escapeHtml(info.zone||'Sin dato')} · Terreno: ${escapeHtml(info.terrain||'Sin dato')}<br>Seguridad: ${safety} · Combate: ${unsafe?'PK':'No PK'}${info.restrict?' · Restricción: '+escapeHtml(info.restrict):''}`;const exitHtml=exits.length?`<hr><strong>Conexiones (${exits.length})</strong><br>${exits.map(map=>`<button class=\"go-map\" data-map=\"${map}\">Mapa ${map}</button>`).join(' ')}`:'<hr><strong>Conexiones: 0</strong>';const sections=LAYERS.map(layer=>layerDetails(layer,id)).filter(Boolean);detailsContent.innerHTML=`<div id=\"detailsSummary\">${status}</div><div id=\"detailsExpanded\">${exitHtml}${sections.length?'<hr>'+sections.join('<hr>'):''}</div>`;detailsContent.querySelectorAll('.go-map').forEach(button=>button.onclick=()=>focusMap(Number(button.dataset.map)));}",
            "function focusMap(id){const index=mapCells.findIndex(cell=>Number(cell.dataset.map)===Number(id));if(index<0)return;const col=index%COLS,row=Math.floor(index/COLS);scale=Math.max(scale,.35);panX=viewport.clientWidth/2-(col+.5)*TILE_W*scale;panY=viewport.clientHeight/2-(row+.5)*TILE_H*scale;apply();showMapDetails(mapCells[index]);}",
            "function selectMapCell(cell){document.querySelectorAll('.selected').forEach(node=>node.classList.remove('selected'));cell.classList.add('selected');}",
            "function mapCellAt(clientX,clientY){const element=document.elementFromPoint(clientX,clientY);return element?element.closest('.map-cell'):null;}",
            "mapCells=Array.from(document.querySelectorAll('.map-cell'));mapCells.forEach(cell=>{cell.querySelectorAll('img').forEach(image=>{image.addEventListener('load',scheduleRender);image.addEventListener('error',scheduleRender);});cell.addEventListener('click',()=>{if(!moved)selectMapCell(cell);});});",
            "viewport.addEventListener('dblclick',event=>{const cell=mapCellAt(event.clientX,event.clientY);if(!cell)return;event.preventDefault();showMapDetails(cell);});",
            "const search=document.getElementById('search'),searchResults=document.getElementById('search-results');function normalized(value){return String(value).normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();}search.addEventListener('input',()=>{const query=normalized(search.value.trim());searchResults.innerHTML='';if(!query){searchResults.style.display='none';return;}const matches=SEARCH_ITEMS.filter(item=>normalized(item.label+' '+item.type+' '+item.map).includes(query)).slice(0,40);searchResults.style.display='block';matches.forEach(item=>{const button=document.createElement('button');button.className='search-result';button.textContent=`${item.label} (Mapa ${item.map})`;button.onclick=()=>{focusMap(item.map);searchResults.style.display='none';};searchResults.appendChild(button);});if(!matches.length)searchResults.textContent='Sin resultados';});",
            "addEventListener('keydown',event=>{if(event.key==='F1'){event.preventDefault();settingsBackdrop.classList.contains('open')?closeSettings(true):openSettings();return;}if(event.key==='Escape'){if(settingsBackdrop.classList.contains('open')){closeSettings(true);return;}document.querySelectorAll('.selected').forEach(n=>n.classList.remove('selected'));details.style.display='none';searchResults.style.display='none';search.blur();hideMarkerTooltip();}});",
            "addEventListener('resize',()=>{if(scale<0.15)fit();else scheduleRender();});",
            "centerAtScale(.25);",
            "</script>",
            "</body>",
            "</html>",
            "",
        ])
        temporary = target.with_suffix(".htm.tmp")
        with temporary.open("w", encoding="utf-8", newline="") as output:
            output.write("\r\n".join(lines))
        temporary.replace(target)
        return target

    def save_world(self) -> None:
        if not self.interface_dir:
            messagebox.showerror(
                "Guardar mundos",
                "No se encontró Recursos/ui/maps. No se guardó ningún cambio para evitar que los datos y la imagen queden desincronizados.",
            )
            return
        self.interface_dir.mkdir(parents=True, exist_ok=True)
        source_folder = "render200x200" if (self.base_dir / "render200x200").is_dir() else "render"
        self.missing_tiles.clear()
        self.alternative_tiles.clear()
        exports = [
            (self.interface_dir / f"world{world_id}.png", self.render_world(world, 200, source_folder))
            for world_id, world in enumerate(self.data.worlds[:3], start=1)
        ]
        self.data.save()
        for target, image in exports:
            image.save(target, format="PNG")
        index_path = self.write_world_index()
        self.changed = False
        exported_paths = "\n".join(str(target) for target, _image in exports)
        messagebox.showinfo(
            "Guardar mundos",
            f"WorldData, imágenes del cliente C++ e índice HTML guardados:\n\n"
            f"{self.data_file}\n{exported_paths}\n{index_path}",
        )

    def _canvas_click(self, event: tk.Event) -> None:
        x = int(self.canvas.canvasx(event.x)) - self.image_offset_x
        y = int(self.canvas.canvasy(event.y)) - self.image_offset_y
        col = x // TILE_SIZE
        row = y // TILE_SIZE
        if col < 0 or row < 0 or col >= self.world.ancho or row >= self.world.alto:
            return
        index = col + row * self.world.ancho
        tile_id = self.world.map_indices[index]
        self._draw_selection(col, row)
        self._set_status(f"Mundo N: {self.selected_world + 1} - Mapa: {tile_id}")

        if self.translate_var.get() and not self.translating:
            self.translating = True
            self.temp_tile = tile_id
            self.temp_index = index
            self._set_status("Seleccione destino...")
            return

        if self.translating:
            assert self.temp_index is not None and self.temp_tile is not None
            self.world.map_indices[self.temp_index], self.world.map_indices[index] = self.world.map_indices[index], self.temp_tile
            self.translating = False
            self.changed = True
            self.render_current()
            return

        if self.empty_var.get() or (event.num == 3 and bool(event.state & 0x0001)):
            self._set_tile(index, EMPTY_TILE)
            return
        if self.water_var.get():
            self._set_tile(index, WATER_TILE)
            return
        if event.num == 3:
            value = simpledialog.askinteger("Nuevo índice", "Ingrese nuevo índice de mapa:", parent=self)
            if value is not None:
                self._set_tile(index, value)

    def _set_tile(self, index: int, value: int) -> None:
        self.world.map_indices[index] = value
        self.changed = True
        self.render_current()

    def _draw_selection(self, col: int, row: int) -> None:
        self.canvas.delete("selection")
        x0 = self.image_offset_x + col * TILE_SIZE
        y0 = self.image_offset_y + row * TILE_SIZE
        self.canvas.create_rectangle(x0, y0, x0 + TILE_SIZE, y0 + TILE_SIZE, outline="red", width=2, tags="selection")

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)

    def _on_close(self) -> None:
        if self.changed:
            ok = messagebox.askyesno("No se guardó", "No se han guardado los cambios. ¿Seguro desea salir?")
            if not ok:
                return
        self.destroy()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Mapa Mundo migrado de VB6 a Python/Tkinter")
    parser.add_argument("--base-dir", default=None, help="Carpeta base del tool. Si se omite, se autodetecta.")
    parser.add_argument("--data-file", default=None, help="Ruta opcional a mapsworlddata.dat")
    parser.add_argument("--web-output", default=None, help="Carpeta de salida del sitio web")
    parser.add_argument("--database", default=None, help="Base map_content.sqlite generada por el WE")
    parser.add_argument("--reset-config", action="store_true", help="Borra mapa_mundo.ini y vuelve a pedir/autodetectar rutas")
    args = parser.parse_args(argv)

    script_dir = application_dir()
    ini_path = script_dir / APP_INI
    if args.reset_config and ini_path.exists():
        ini_path.unlink()

    resolver = AppPaths(script_dir)
    paths = resolver.resolve(
        Path(args.base_dir).resolve() if args.base_dir else None,
        Path(args.data_file).resolve() if args.data_file else None,
        Path(args.web_output).resolve() if args.web_output else None,
        Path(args.database).resolve() if args.database else None,
    )
    app = MapaMundoApp(paths)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

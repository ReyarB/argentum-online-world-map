from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_web", ROOT / "scripts" / "build_web.py")
assert SPEC is not None and SPEC.loader is not None
BUILD_WEB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_WEB)


class ExtendedMapImageTests(unittest.TestCase):
    def test_merges_legacy_base_and_transparent_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            minimaps = root / "minimapas"
            overflows = root / "desbordes"
            minimaps.mkdir()
            overflows.mkdir()
            Image.new("RGB", (4, 6), "red").save(minimaps / "Mapa7.bmp")
            Image.new("RGB", (2, 2), "yellow").save(minimaps / "Mapa7.png")
            overflow = Image.new("RGBA", (8, 10), (0, 0, 0, 0))
            overflow.putpixel((0, 0), (0, 0, 255, 255))
            overflow.save(overflows / "Mapa7.png")

            result = BUILD_WEB.extended_map_image(minimaps, overflows, 7)

            self.assertIsNotNone(result)
            image, source_kind = result
            self.assertEqual(source_kind, "legacy-merged")
            self.assertEqual(image.size, (8, 10))
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))
            self.assertEqual(image.getpixel((2, 2)), (255, 0, 0, 255))

    def test_prefers_unified_png(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            minimaps = root / "minimapas"
            overflows = root / "desbordes"
            minimaps.mkdir()
            overflows.mkdir()
            Image.new("RGBA", (600, 650), "green").save(minimaps / "Mapa9.png")
            Image.new("RGB", (4, 6), "red").save(minimaps / "Mapa9.bmp")

            result = BUILD_WEB.extended_map_image(minimaps, overflows, 9)

            self.assertIsNotNone(result)
            image, source_kind = result
            self.assertEqual(source_kind, "unified")
            self.assertEqual(image.size, (600, 650))
            self.assertEqual(image.getpixel((0, 0)), (0, 128, 0, 255))


class InteriorDiscoveryTests(unittest.TestCase):
    def test_discovers_only_interiors_reachable_from_internal_surface_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "map_content.sqlite"
            connection = sqlite3.connect(database)
            connection.executescript(
                "CREATE TABLE maps(map_id INTEGER,file_name TEXT,file_path TEXT);"
                "CREATE TABLE map_exits(map_id INTEGER,file_name TEXT,x INTEGER,y INTEGER,"
                "to_map INTEGER,to_x INTEGER,to_y INTEGER);"
            )
            rows = [(map_id, f"mapa{map_id}.csm", f"C:/active/mapa{map_id}.csm")
                    for map_id in (1, 2, 10, 11, 98, 99)]
            connection.executemany("INSERT INTO maps VALUES(?,?,?)", rows)
            connection.executemany(
                "INSERT INTO map_exits VALUES(?,?,?,?,?,?,?)",
                [
                    (1, "mapa1.csm", 88, 40, 2, 14, 40),
                    (1, "mapa1.csm", 50, 50, 10, 20, 20),
                    (10, "mapa10.csm", 88, 40, 11, 14, 40),
                    (11, "mapa11.csm", 13, 40, 2, 87, 40),
                    (99, "mapa99.csm", 50, 50, 98, 20, 20),
                ],
            )
            connection.commit()
            connection.close()

            discovered = BUILD_WEB.discover_interior_map_ids(database, {1, 2})

            self.assertEqual(discovered, {10, 11})

    def test_clusters_adjacent_tiles_but_keeps_separate_entrances(self) -> None:
        generator = BUILD_WEB.load_generator()

        exits = generator.cluster_map_exits([
            (65, 37, 397, 49, 11),
            (66, 37, 397, 50, 11),
            (67, 37, 397, 51, 11),
            (20, 60, 397, 30, 30),
        ])

        self.assertEqual(len(exits), 2)
        self.assertEqual(exits[0]["x"], 66)
        self.assertEqual(exits[0]["tiles"], 3)
        self.assertFalse(exits[0]["border"])

    def test_builds_an_interior_world_from_border_transfers(self) -> None:
        generator = BUILD_WEB.load_generator()
        exits = {
            10: [
                {"x": 50, "y": 91, "toMap": 11, "toX": 50, "toY": 11,
                 "tiles": 3, "border": True},
                {"x": 40, "y": 40, "toMap": 12, "toX": 20, "toY": 20,
                 "tiles": 1, "border": False},
            ],
            11: [
                {"x": 50, "y": 10, "toMap": 10, "toX": 50, "toY": 90,
                 "tiles": 3, "border": True},
            ],
        }

        components, component_by_map = generator.build_interior_layouts(
            exits, {1, 2}, {1, 2, 10, 11, 12}
        )

        joined = components[component_by_map[10]]
        self.assertEqual(joined["cols"], 1)
        self.assertEqual(joined["rows"], 2)
        self.assertEqual({item["id"] for item in joined["maps"]}, {10, 11})
        isolated = components[component_by_map[12]]
        self.assertEqual(isolated["maps"], [{"id": 12, "col": 0, "row": 0}])


if __name__ == "__main__":
    unittest.main()

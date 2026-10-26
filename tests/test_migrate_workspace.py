from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migrate_workspace", ROOT / "scripts" / "migrate_workspace.py"
)
assert SPEC is not None and SPEC.loader is not None
MIGRATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATE)


class WorkspaceMigrationTests(unittest.TestCase):
    def test_replaces_only_legacy_workspace_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "resources" / "minimapas"
            source_overflows = root / "resources" / "desbordes"
            target = root / "workspace" / "minimapas"
            target_overflows = root / "workspace" / "desbordes"
            for directory in (source, source_overflows, target, target_overflows):
                directory.mkdir(parents=True, exist_ok=True)

            source_base = source / "Mapa7.bmp"
            Image.new("RGB", (4, 6), "red").save(source_base)
            overflow = Image.new("RGBA", (8, 10), (0, 0, 0, 0))
            overflow.putpixel((0, 0), (0, 0, 255, 255))
            overflow.save(source_overflows / "Mapa7.png")
            Image.new("RGB", (4, 6), "black").save(target / "Mapa7.bmp")
            Image.new("RGBA", (8, 10), "yellow").save(
                target_overflows / "Mapa7.png"
            )
            Image.new("RGBA", (8, 10), "green").save(
                target_overflows / "Mapa99.png"
            )

            migrated, merged, stems = MIGRATE.migrate_minimaps(
                source, source_overflows, target
            )
            removed = MIGRATE.remove_legacy_workspace_overflows(
                target_overflows, stems
            )

            self.assertEqual((migrated, merged, removed), (1, 1, 1))
            self.assertTrue(source_base.is_file())
            self.assertTrue((source_overflows / "Mapa7.png").is_file())
            self.assertFalse((target / "Mapa7.bmp").exists())
            self.assertFalse((target_overflows / "Mapa7.png").exists())
            self.assertTrue((target_overflows / "Mapa99.png").is_file())
            with Image.open(target / "Mapa7.png") as image:
                self.assertEqual(image.size, (8, 10))
                self.assertEqual(image.convert("RGBA").getpixel((0, 0)),
                                 (0, 0, 255, 255))

    def test_migrates_legacy_workspace_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            minimaps = workspace / "minimapas"
            overflows = workspace / "desbordes"
            minimaps.mkdir()
            overflows.mkdir()
            Image.new("RGB", (4, 6), "red").save(minimaps / "Mapa8.bmp")
            Image.new("RGB", (2, 2), "yellow").save(minimaps / "mapa8.png")
            overflow = Image.new("RGBA", (8, 10), (0, 0, 0, 0))
            overflow.putpixel((7, 9), (0, 0, 255, 255))
            overflow.save(overflows / "Mapa8.png")

            migrated, merged, stems = MIGRATE.migrate_minimaps(
                minimaps, overflows, minimaps
            )
            removed = MIGRATE.remove_legacy_workspace_overflows(overflows, stems)

            self.assertEqual((migrated, merged, removed), (1, 1, 1))
            self.assertFalse((minimaps / "Mapa8.bmp").exists())
            self.assertFalse(overflows.exists())
            with Image.open(minimaps / "Mapa8.png") as image:
                self.assertEqual(image.size, (8, 10))
                self.assertEqual(image.convert("RGBA").getpixel((7, 9)),
                                 (0, 0, 255, 255))


if __name__ == "__main__":
    unittest.main()

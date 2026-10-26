from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()

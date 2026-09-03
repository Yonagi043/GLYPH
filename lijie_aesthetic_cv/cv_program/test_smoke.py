"""Minimal deterministic smoke tests; run with `python -m unittest -v`."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from aesthetic_cv import DIMENSIONS, analyse, write_result


class AestheticCVSmokeTest(unittest.TestCase):
    def test_single_image_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "shape.png"
            output = root / "result"
            image = np.full((256, 256, 3), 255, np.uint8)
            cv2.rectangle(image, (72, 52), (184, 204), (0, 0, 0), 12)
            cv2.line(image, (72, 128), (184, 128), (0, 0, 0), 10)
            self.assertTrue(cv2.imwrite(str(image_path), image))

            result = analyse(image_path)
            write_result(result, output)

            self.assertEqual(set(result["dimension_scores"]), set(DIMENSIONS))
            self.assertGreaterEqual(result["total_score"], 0.0)
            self.assertLessEqual(result["total_score"], 100.0)
            self.assertTrue((output / "result.json").exists())
            self.assertTrue((output / "result.csv").exists())
            self.assertTrue((output / "debug.png").exists())


if __name__ == "__main__":
    unittest.main()

import unittest

import numpy as np

from ai.segmentation.waternet import WaterNetSegmenter


class WaterNetAdaptiveTests(unittest.TestCase):
    def test_fragmentation_refine_merges_narrow_water_gaps(self):
        mask = np.zeros((120, 120), dtype=bool)
        expected = np.zeros_like(mask)

        # Two large water lobes separated by a narrow four-pixel gap.
        mask[30:90, 20:58] = True
        mask[30:90, 62:100] = True
        expected[25:95, 15:105] = True

        segmenter = WaterNetSegmenter(context_buffer_meters=150.0)
        refined = segmenter._adaptive_fragmentation_refine(mask, expected)

        before = segmenter._fragmentation_metrics(mask)
        after = segmenter._fragmentation_metrics(refined)

        self.assertLess(
            after["fragmentation_index"],
            before["fragmentation_index"],
        )
        self.assertGreaterEqual(
            np.sum(refined & expected) / np.sum(refined),
            0.99,
        )


if __name__ == "__main__":
    unittest.main()

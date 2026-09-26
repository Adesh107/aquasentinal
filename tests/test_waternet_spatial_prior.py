import unittest
from types import SimpleNamespace

import numpy as np
from rasterio.transform import from_origin
from rasterio.warp import transform_geom

from ai.segmentation.waternet import WaterNetSegmenter


class WaterNetSpatialPriorTests(unittest.TestCase):
    def _make_ard(self):
        height = width = 100
        transform = from_origin(0.0, 1000.0, 10.0, 10.0)

        b02 = np.full((height, width), 0.02, dtype=np.float32)
        b03 = np.full((height, width), 0.01, dtype=np.float32)
        b04 = np.full((height, width), 0.01, dtype=np.float32)
        b08 = np.full((height, width), 0.40, dtype=np.float32)
        b11 = np.full((height, width), 0.30, dtype=np.float32)
        scl = np.zeros((height, width), dtype=np.uint8)

        # Main water body inside the stored footprint.
        b03[30:70, 30:70] = 0.06
        b04[30:70, 30:70] = 0.03
        b08[30:70, 30:70] = 0.08
        b11[30:70, 30:70] = 0.02
        scl[30:70, 30:70] = 6

        # Large, disconnected spectral-water patch well outside the expected
        # footprint and outside the 150 m context buffer.
        b03[5:25, 75:95] = 0.06
        b04[5:25, 75:95] = 0.03
        b08[5:25, 75:95] = 0.08
        b11[5:25, 75:95] = 0.02
        scl[5:25, 75:95] = 6

        return SimpleNamespace(
            water_body_id="WB_TEST",
            observation_date="2024-03-19T05:26:49Z",
            satellite_name="Sentinel-2B",
            cloud_percentage=0.0,
            source_reference="SYNTHETIC_TEST_SCENE",
            pinned_bands=["B02", "B03", "B04", "B08", "B11"],
            bands={"B02": b02, "B03": b03, "B04": b04, "B08": b08, "B11": b11},
            scl=scl,
            profile={
                "driver": "GTiff",
                "dtype": "float32",
                "count": 5,
                "height": height,
                "width": width,
                "crs": "EPSG:32643",
                "transform": transform,
            },
            height=height,
            width=width,
            resolution_m=10.0,
            observation_metadata=None,
        )

    def _expected_geometry(self):
        # UTM rectangle matching the central water region: x=300..700,
        # y=300..700. Transform it to the WGS84 geometry contract expected by
        # the segmenter.
        geom_utm = {
            "type": "Polygon",
            "coordinates": [[
                [300.0, 300.0],
                [700.0, 300.0],
                [700.0, 700.0],
                [300.0, 700.0],
                [300.0, 300.0],
            ]],
        }
        return transform_geom(
            "EPSG:32643",
            "EPSG:4326",
            geom_utm,
        )

    def test_spatial_prior_removes_remote_false_component(self):
        ard = self._make_ard()
        result = WaterNetSegmenter().segment(
            ard,
            expected_water_geometry={
                "type": "Feature",
                "geometry": self._expected_geometry(),
            },
        )

        self.assertGreater(result.quality_report.expected_water_pixels, 0)
        self.assertGreater(result.quality_report.water_pixels, 0)
        self.assertGreaterEqual(
            result.quality_report.detected_inside_expected_pct,
            99.0,
        )
        self.assertLess(
            result.quality_report.out_of_footprint_pct,
            1.0,
        )
        self.assertIsNone(result.quality_report.spatial_prior_warning)

        # The remote water-like patch is 300+ m away from the stored footprint,
        # so it must not survive the context-prior restriction.
        self.assertLess(result.water_area_km2, 0.25)

    def test_segmentation_without_prior_remains_supported(self):
        ard = self._make_ard()
        result = WaterNetSegmenter().segment(ard)

        self.assertGreater(result.quality_report.water_pixels, 0)
        self.assertEqual(result.quality_report.expected_water_pixels, 0)
        self.assertEqual(result.quality_report.overlap_water_pixels, 0)


if __name__ == "__main__":
    unittest.main()

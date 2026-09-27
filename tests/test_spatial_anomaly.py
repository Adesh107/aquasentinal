from rasterio.transform import from_origin
import numpy as np

from ai.anomaly.spatial import SpatialAnomalyMapper


def test_spatial_anomaly_mapper_creates_geojson_region():
    shape = (6, 6)
    water_mask = np.ones(shape, dtype=bool)
    confidence = np.full(shape, 0.8, dtype=np.float32)

    base = np.full(shape, 0.2, dtype=np.float32)
    hotspot = np.zeros(shape, dtype=np.float32)
    hotspot[2:4, 2:4] = 0.3

    spatial_maps = {
        "turbidity": base,
        "chlorophyll": base + hotspot,
        "algal": base + hotspot,
    }
    baseline = {
        "turbidity": {"mean": 0.2, "std": 0.05},
        "chlorophyll": {"mean": 0.2, "std": 0.05},
        "algal": {"mean": 0.2, "std": 0.05},
    }
    profile = {
        "crs": "EPSG:32643",
        "transform": from_origin(500000, 2000000, 10, 10),
    }

    result = SpatialAnomalyMapper().build(
        spatial_maps=spatial_maps,
        water_mask=water_mask,
        confidence_map=confidence,
        baseline_stats=baseline,
        profile=profile,
    )

    assert result.anomaly_regions is not None
    assert result.anomaly_regions["type"] == "FeatureCollection"
    assert len(result.anomaly_regions["features"]) == 1
    assert result.anomalous_pixels == 4
    assert result.affected_area_km2 == 0.0004
    assert result.confidence == 0.8
    assert result.anomaly_regions["features"][0]["properties"]["dominant_indicator"] == "chlorophyll"


def test_spatial_anomaly_mapper_returns_empty_without_pixel_maps():
    mapper = SpatialAnomalyMapper()
    result = mapper.build(
        spatial_maps={},
        water_mask=np.ones((3, 3), dtype=bool),
        confidence_map=np.ones((3, 3), dtype=np.float32),
        baseline_stats={},
        profile={
            "crs": "EPSG:32643",
            "transform": from_origin(500000, 2000000, 10, 10),
        },
    )

    assert result.anomaly_regions is None
    assert result.affected_area_km2 is None
    assert result.anomalous_pixels == 0

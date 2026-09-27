"""
Spatial anomaly localization.

Builds a pixel-level anomaly mask from the current observation's normalized
spectral composites against the historical baseline's global statistics.

This is intentionally labeled a proxy:
- it is not a per-pixel historical baseline;
- it does not spatially resolve water-area change;
- it uses only indicators with real per-pixel values from the spectral stage.

No synthetic copy/scaled water-boundary geometry is generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np
from rasterio import features
from rasterio.warp import transform_geom
from scipy import ndimage
from shapely.geometry import shape


@dataclass
class SpatialAnomalyResult:
    anomaly_regions: Dict[str, Any] | None
    affected_area_km2: float | None
    confidence: float | None
    anomalous_pixels: int
    spatial_mode: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_regions": self.anomaly_regions,
            "affected_area_km2": self.affected_area_km2,
            "confidence": self.confidence,
            "anomalous_pixels": self.anomalous_pixels,
            "spatial_mode": self.spatial_mode,
        }


class SpatialAnomalyMapper:
    """Create explainable GeoJSON regions from pixel-level spectral composites."""

    Z_SCORE_THRESHOLD = 1.5
    # Same indicator weights as the scalar detector, renormalized because
    # water-area anomaly is not spatially resolved.
    WEIGHTS = {
        "turbidity": 0.30,
        "chlorophyll": 0.30,
        "algal": 0.25,
    }
    PIXEL_SCORE_THRESHOLD = 0.50
    MIN_COMPONENT_PIXELS = 4

    def build(
        self,
        spatial_maps: Dict[str, np.ndarray],
        water_mask: np.ndarray,
        confidence_map: np.ndarray,
        baseline_stats: Dict[str, Dict[str, float]],
        profile: Dict[str, Any],
    ) -> SpatialAnomalyResult:
        if not spatial_maps:
            return self._empty()

        available = [
            name for name in self.WEIGHTS
            if name in spatial_maps and name in baseline_stats
        ]
        if not available:
            return self._empty()

        score = np.zeros(water_mask.shape, dtype=np.float32)
        weight_total = 0.0
        indicator_scores: Dict[str, np.ndarray] = {}

        for name in available:
            values = np.asarray(spatial_maps[name], dtype=np.float32)
            if values.shape != water_mask.shape:
                raise ValueError(
                    f"Spatial map '{name}' shape {values.shape} does not match "
                    f"water mask shape {water_mask.shape}."
                )

            mean = float(baseline_stats[name].get("mean", 0.0))
            std = float(baseline_stats[name].get("std", 0.0))

            if std < 1e-8:
                z = np.where(
                    np.abs(values - mean) >= 1e-6,
                    3.0,
                    0.0,
                )
            else:
                z = np.abs((values - mean) / std)

            with np.errstate(invalid="ignore"):
                indicator_score = (
                    1.0
                    - 1.0 / (1.0 + (z / self.Z_SCORE_THRESHOLD) ** 2)
                )

            indicator_score = np.nan_to_num(
                indicator_score,
                nan=0.0,
                posinf=1.0,
                neginf=0.0,
            ).astype(np.float32)

            indicator_scores[name] = indicator_score
            weight = self.WEIGHTS[name]
            score += weight * indicator_score
            weight_total += weight

        if weight_total <= 0:
            return self._empty()

        score /= weight_total
        score[~water_mask] = 0.0

        anomaly_mask = score >= self.PIXEL_SCORE_THRESHOLD
        anomaly_mask &= water_mask

        # Remove tiny isolated components. This does not create new regions;
        # it only suppresses pixel noise in the already-derived anomaly mask.
        labeled, num_components = ndimage.label(anomaly_mask)
        if num_components:
            sizes = ndimage.sum(
                anomaly_mask,
                labeled,
                range(1, num_components + 1),
            )
            keep = np.zeros(num_components + 1, dtype=bool)
            for idx, size in enumerate(sizes, start=1):
                if int(size) >= self.MIN_COMPONENT_PIXELS:
                    keep[idx] = True
            anomaly_mask = keep[labeled]

        anomalous_pixels = int(np.sum(anomaly_mask))
        if anomalous_pixels == 0:
            return self._empty()

        transform = profile["transform"]
        pixel_area_km2 = abs(
            float(transform.a) * float(transform.e)
            - float(transform.b) * float(transform.d)
        ) / 1_000_000.0

        confidence_values = np.asarray(confidence_map, dtype=np.float32)
        valid_conf = confidence_values[anomaly_mask]
        confidence = (
            round(float(np.mean(valid_conf)), 4)
            if valid_conf.size
            else None
        )

        features = []
        shapes_gen = features.shapes(
            anomaly_mask.astype(np.uint8),
            mask=anomaly_mask,
            transform=transform,
            connectivity=8,
        )

        for geom, value in shapes_gen:
            if value != 1:
                continue

            native_geom = shape(geom)
            native_pixel_area = abs(
                float(transform.a) * float(transform.e)
                - float(transform.b) * float(transform.d)
            )
            pixel_count = int(round(native_geom.area / native_pixel_area))
            if pixel_count < self.MIN_COMPONENT_PIXELS:
                continue

            mask_component = self._component_mask_from_geometry(
                native_geom,
                anomaly_mask.shape,
                transform,
            )
            component_scores = score[mask_component]
            component_conf = confidence_values[mask_component]

            means = {}
            for name, indicator_score in indicator_scores.items():
                means[name] = float(np.mean(indicator_score[mask_component]))

            dominant = max(means, key=means.get)
            reprojected = transform_geom(
                src_crs=profile["crs"],
                dst_crs="EPSG:4326",
                geom=geom,
            )

            features.append(
                {
                    "type": "Feature",
                    "geometry": reprojected,
                    "properties": {
                        "spatial_mode": "global_baseline_pixel_proxy",
                        "pixel_count": pixel_count,
                        "area_km2": round(pixel_count * pixel_area_km2, 6),
                        "mean_anomaly_score": round(float(np.mean(component_scores)), 4),
                        "mean_segmentation_confidence": round(float(np.mean(component_conf)), 4),
                        "dominant_indicator": dominant,
                        "indicator_scores": {
                            name: round(value, 4)
                            for name, value in means.items()
                        },
                    },
                }
            )

        if not features:
            return self._empty()

        regions = {
            "type": "FeatureCollection",
            "features": features,
        }
        affected_area = round(anomalous_pixels * pixel_area_km2, 6)

        return SpatialAnomalyResult(
            anomaly_regions=regions,
            affected_area_km2=affected_area,
            confidence=confidence,
            anomalous_pixels=anomalous_pixels,
            spatial_mode="global_baseline_pixel_proxy",
        )

    @staticmethod
    def _component_mask_from_geometry(
        geometry,
        shape_xy: tuple[int, int],
        transform,
    ) -> np.ndarray:
        return features.geometry_mask(
            [geometry],
            out_shape=shape_xy,
            transform=transform,
            invert=True,
            all_touched=False,
        )

    @staticmethod
    def _empty() -> SpatialAnomalyResult:
        return SpatialAnomalyResult(
            anomaly_regions=None,
            affected_area_km2=None,
            confidence=None,
            anomalous_pixels=0,
            spatial_mode="global_baseline_pixel_proxy",
        )

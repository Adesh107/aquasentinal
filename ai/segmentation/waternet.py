"""
WaterNet: Water Surface Segmentation Module.
Strictly dedicated to binary water mask generation and water boundary polygonization.
NEVER used as a turbidity or chlorophyll model.

References established surface-water segmentation principles from satellite-image-deep-learning/techniques:
- Multi-spectral index fusion (MNDWI, NDWI, Red-SWIR absorption)
- Morphological spatial filtering and connected component analysis
- Strict mask quality guard (water pixel %, fragmentation index, cloud-mask overlap)
- Vectorization into GeoJSON MultiPolygon (EPSG:4326)
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json

import numpy as np
from scipy import ndimage
import rasterio
from rasterio import features
from rasterio.warp import transform_geom
import shapely.geometry
from shapely.geometry import shape, mapping, MultiPolygon, Polygon
from shapely.ops import unary_union

from ai.preprocessing.preprocessor import AnalysisReadyData

logger = logging.getLogger("AquaSentinel.WaterNet")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [WaterNet] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# SCL cloud & shadow classes
SCL_CLOUD_SHADOW_CLASSES = [3, 8, 9, 10]  # 3: Cloud shadows, 8: Cloud medium, 9: Cloud high, 10: Cirrus


@dataclass
class MaskQualityReport:
    """Quality diagnostic report for water mask validation guard."""
    is_valid: bool
    status: str  # "ok", "degraded", "low_confidence_mask", "excessive_cloud_overlap"
    water_pixels: int
    total_pixels: int
    water_pixel_pct: float
    water_area_km2: float
    num_connected_components: int
    largest_component_pixels: int
    largest_component_ratio: float  # largest component / total water
    fragmentation_index: float  # 1.0 - largest_component_ratio
    cloud_overlap_pixels: int
    cloud_overlap_pct: float

    # Spatial-prior diagnostics. The expected footprint is a monitoring prior,
    # not ground truth, so these values are reported separately from the
    # spectral quality guard.
    expected_water_pixels: int = 0
    overlap_water_pixels: int = 0
    detected_inside_expected_pct: float = 0.0
    expected_coverage_pct: float = 0.0
    out_of_footprint_pct: float = 0.0
    spatial_prior_warning: Optional[str] = None

    failure_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WaterSegmentationResult:
    """Output of WaterNet segmentation."""
    water_body_id: str
    observation_date: str
    source_reference: str
    water_mask: np.ndarray  # 2D boolean array (True = Water)
    confidence_map: np.ndarray  # 2D float32 [0.0, 1.0]
    quality_report: MaskQualityReport
    boundary_geojson: Dict[str, Any]  # GeoJSON Feature/Geometry in EPSG:4326
    profile: Dict[str, Any]  # Rasterio profile of the mask
    water_area_km2: float


class WaterNetSegmenter:
    """
    Water surface segmentation engine.
    Strictly performs spatial water segmentation and quality boundary extraction.
    """

    def __init__(
        self,
        min_water_pixel_pct: float = 0.5,
        max_water_pixel_pct: float = 95.0,
        max_fragmentation_index: float = 0.50,
        min_largest_component_ratio: float = 0.40,
        max_cloud_overlap_pct: float = 20.0,
        context_buffer_meters: float = 150.0,
        mndwi_threshold: float = 0.05,
        ndwi_threshold: float = 0.02,
        min_component_area_pixels: int = 15,  # Filters 1500m2 specks
    ):
        self.min_water_pixel_pct = min_water_pixel_pct
        self.max_water_pixel_pct = max_water_pixel_pct
        self.max_fragmentation_index = max_fragmentation_index
        self.min_largest_component_ratio = min_largest_component_ratio
        self.max_cloud_overlap_pct = max_cloud_overlap_pct
        self.context_buffer_meters = context_buffer_meters
        self.mndwi_threshold = mndwi_threshold
        self.ndwi_threshold = ndwi_threshold
        self.min_component_area_pixels = min_component_area_pixels

    def segment(
        self,
        ard: AnalysisReadyData,
        expected_water_geometry: Optional[Dict[str, Any]] = None,
    ) -> WaterSegmentationResult:
        """
        Segment water surface from analysis-ready bands and apply quality guard.
        
        GUARD: Checks % water pixels, fragmentation, and cloud-mask overlap.
        If confidence criteria fail, the quality report marks is_valid=False with
        status='low_confidence_mask' / 'degraded' and explicit explanations.
        """
        logger.info(f"Executing WaterNet segmentation for {ard.water_body_id}...")

        # Extract calibrated bands
        b02 = ard.bands["B02"]  # Blue
        b03 = ard.bands["B03"]  # Green
        b04 = ard.bands["B04"]  # Red
        b08 = ard.bands["B08"]  # NIR
        b11 = ard.bands["B11"]  # SWIR-1

        # 1. Compute Spectral Water Indices
        # MNDWI: (Green - SWIR) / (Green + SWIR)
        mndwi_denom = b03 + b11
        mndwi = np.where(mndwi_denom > 1e-6, (b03 - b11) / np.maximum(mndwi_denom, 1e-6), -1.0)

        # NDWI: (Green - NIR) / (Green + NIR)
        ndwi_denom = b03 + b08
        ndwi = np.where(ndwi_denom > 1e-6, (b03 - b08) / np.maximum(ndwi_denom, 1e-6), -1.0)

        # Shadow & dark vegetation discrimination:
        # Water has low NIR (< 0.15) and Green > Red or MNDWI > threshold
        nir_low = b08 < 0.18
        swir_low = b11 < 0.15

        # Initial Water Probability / Decision surface
        water_cand_1 = (mndwi > self.mndwi_threshold) & nir_low
        water_cand_2 = (ndwi > self.ndwi_threshold) & (b03 > b04) & swir_low
        raw_water_mask = water_cand_1 | water_cand_2

        # Cross-reference with SCL water class if available
        if ard.scl is not None:
            scl_water = (ard.scl == 6)  # SCL class 6 = Water
            # Agreement or strong spectral index
            raw_water_mask = raw_water_mask | (scl_water & (mndwi > -0.05))

        # Apply the selected water body's known footprint as a spatial prior.
        # The prior is buffered so genuine shoreline movement can still be
        # detected outside the stored/reference polygon.
        expected_mask: Optional[np.ndarray] = None
        context_mask: Optional[np.ndarray] = None
        if expected_water_geometry is not None:
            expected_mask, context_mask = self._rasterize_expected_geometry(
                expected_water_geometry,
                ard.profile,
                (ard.height, ard.width),
            )
            raw_water_mask &= context_mask

        # 2. Morphological Spatial Cleanup
        # Remove small disconnected noise specks, close tiny shoreline gaps,
        # and keep components that are anchored to the known footprint or are
        # sufficiently large and close to it.
        cleaned_mask = self._morphological_refine(raw_water_mask)
        if expected_mask is not None:
            cleaned_mask = self._anchor_components_to_footprint(
                cleaned_mask,
                expected_mask,
            )

        # 3. Calculate Confidence Map
        confidence_map = self._compute_confidence_map(mndwi, ndwi, b08, cleaned_mask, ard.scl)

        # 4. GUARD: Check Mask Quality
        quality_report = self._evaluate_mask_quality(
            cleaned_mask,
            ard,
            expected_mask=expected_mask,
        )
        if not quality_report.is_valid:
            logger.warning(
                f"[GUARD TRIGGERED] Low confidence water mask for {ard.water_body_id}! "
                f"Status: {quality_report.status}, Reasons: {quality_report.failure_reasons}"
            )
        else:
            logger.info(
                f"Water mask passed quality guard. Water Area: {quality_report.water_area_km2:.3f} km² "
                f"({quality_report.water_pixel_pct:.2f}% of AOI)."
            )

        # 5. Vectorize Boundary into EPSG:4326 GeoJSON
        boundary_geojson = self._vectorize_mask_to_geojson(cleaned_mask, ard.profile)

        # Profile for saving mask raster
        mask_profile = ard.profile.copy()
        mask_profile.update(
            count=1,
            dtype="uint8",
            nodata=0,
        )

        return WaterSegmentationResult(
            water_body_id=ard.water_body_id,
            observation_date=ard.observation_date,
            source_reference=ard.source_reference,
            water_mask=cleaned_mask,
            confidence_map=confidence_map,
            quality_report=quality_report,
            boundary_geojson=boundary_geojson,
            profile=mask_profile,
            water_area_km2=quality_report.water_area_km2,
        )

    def _morphological_refine(self, raw_mask: np.ndarray) -> np.ndarray:
        """Removes isolated speckles and fills small shoreline cavities."""
        # 1. Connected components labeling
        labeled_array, num_features = ndimage.label(raw_mask)
        if num_features == 0:
            return np.zeros_like(raw_mask, dtype=bool)

        # Count pixel sizes per component
        component_sizes = ndimage.sum(raw_mask, labeled_array, range(num_features + 1))
        # Keep only components meeting minimum area
        keep_mask = component_sizes >= self.min_component_area_pixels
        keep_mask[0] = False  # Background
        cleaned = keep_mask[labeled_array]

        # 2. Close narrow gaps and fill small shoreline cavities.
        structure = np.ones((3, 3), dtype=bool)
        cleaned = ndimage.binary_closing(cleaned, structure=structure, iterations=1)
        cleaned = ndimage.binary_fill_holes(cleaned)
        return cleaned

    def _anchor_components_to_footprint(
        self,
        mask: np.ndarray,
        expected_mask: np.ndarray,
    ) -> np.ndarray:
        """
        Keep water components that are spatially plausible for the selected
        water body. Core components must overlap the expected footprint.
        Expansion components may survive when they are large enough and close
        to the footprint, preserving limited seasonal shoreline movement.
        """
        labeled, num_components = ndimage.label(mask)
        if num_components == 0:
            return np.zeros_like(mask, dtype=bool)

        near_expected = ndimage.binary_dilation(
            expected_mask,
            iterations=max(1, int(round(self.context_buffer_meters / 10.0))),
        )

        component_sizes = ndimage.sum(
            mask,
            labeled,
            range(1, num_components + 1),
        )

        keep_labels = np.zeros(num_components + 1, dtype=bool)
        expansion_min_pixels = max(self.min_component_area_pixels * 4, 30)

        for label_id, component_size in enumerate(component_sizes, start=1):
            component = labeled == label_id
            overlaps_core = bool(np.any(component & expected_mask))
            is_near_core = bool(np.any(component & near_expected))

            if overlaps_core or (
                is_near_core and component_size >= expansion_min_pixels
            ):
                keep_labels[label_id] = True

        return keep_labels[labeled]

    def _rasterize_expected_geometry(
        self,
        expected_water_geometry: Dict[str, Any],
        profile: Dict[str, Any],
        shape: Tuple[int, int],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Rasterize the stored water-body footprint and a meter-based buffered
        context window onto the analysis grid.
        """
        geometry = expected_water_geometry.get("geometry", expected_water_geometry)
        if not geometry or not geometry.get("type"):
            raise ValueError("Expected water-body geometry is missing or invalid.")

        native_geometry = transform_geom(
            src_crs="EPSG:4326",
            dst_crs=profile["crs"],
            geom=geometry,
        )
        native_shape = shapely.geometry.shape(native_geometry)

        if native_shape.is_empty:
            raise ValueError("Expected water-body geometry is empty.")
        if not native_shape.is_valid:
            native_shape = native_shape.buffer(0)
        if native_shape.is_empty:
            raise ValueError("Expected water-body geometry could not be repaired.")

        buffered_shape = native_shape.buffer(self.context_buffer_meters)

        expected_mask = features.geometry_mask(
            [mapping(native_shape)],
            out_shape=shape,
            transform=profile["transform"],
            invert=True,
            all_touched=True,
        )
        context_mask = features.geometry_mask(
            [mapping(buffered_shape)],
            out_shape=shape,
            transform=profile["transform"],
            invert=True,
            all_touched=True,
        )

        return expected_mask, context_mask

    def _compute_confidence_map(
        self,
        mndwi: np.ndarray,
        ndwi: np.ndarray,
        b08: np.ndarray,
        water_mask: np.ndarray,
        scl: Optional[np.ndarray],
    ) -> np.ndarray:
        """Computes pixel-wise segmentation confidence in [0.0, 1.0]."""
        # Base confidence from MNDWI normalized
        norm_mndwi = np.clip((mndwi + 0.2) / 0.8, 0.0, 1.0)
        # Low NIR boost
        nir_factor = np.clip(1.0 - (b08 / 0.25), 0.0, 1.0)
        conf = 0.6 * norm_mndwi + 0.4 * nir_factor

        if scl is not None:
            # SCL water agreement bonus
            scl_water_bonus = (scl == 6).astype(np.float32) * 0.2
            conf = np.clip(conf + scl_water_bonus, 0.0, 1.0)

        # Water mask modulation
        conf = np.where(water_mask, conf, 0.0).astype(np.float32)
        return conf

    def _evaluate_mask_quality(
        self,
        mask: np.ndarray,
        ard: AnalysisReadyData,
        expected_mask: Optional[np.ndarray] = None,
    ) -> MaskQualityReport:
        """
        Executes strict quality checks on the segmentation mask.
        Evaluates:
        1. Water pixel % vs AOI bounds
        2. Fragmentation index (ratio of largest body to total water)
        3. Cloud & cloud-shadow overlap on water body region
        """
        total_pixels = mask.size
        water_pixels = int(np.sum(mask))
        water_pixel_pct = (water_pixels / total_pixels) * 100.0
        # 10m x 10m = 100 m2 = 1e-4 km2 per pixel
        water_area_km2 = water_pixels * 1e-4

        # Connected component fragmentation
        labeled, num_components = ndimage.label(mask)
        if num_components > 0 and water_pixels > 0:
            sizes = ndimage.sum(mask, labeled, range(1, num_components + 1))
            largest_pixels = int(np.max(sizes))
            largest_ratio = largest_pixels / water_pixels
            fragmentation_index = 1.0 - largest_ratio
        else:
            largest_pixels = 0
            largest_ratio = 0.0
            fragmentation_index = 1.0

        # Cloud overlap on potential water body area
        cloud_overlap_pixels = 0
        cloud_overlap_pct = 0.0
        if ard.scl is not None:
            # Check SCL cloud and shadow classes
            cloud_mask = np.isin(ard.scl, SCL_CLOUD_SHADOW_CLASSES)
            # Overlap in the water region (or adjacent buffer)
            dilated_water = ndimage.binary_dilation(mask, iterations=5)
            cloud_over_water = cloud_mask & dilated_water
            cloud_overlap_pixels = int(np.sum(cloud_over_water))
            ref_denom = max(water_pixels, 1)
            cloud_overlap_pct = (cloud_overlap_pixels / ref_denom) * 100.0

        expected_water_pixels = 0
        overlap_water_pixels = 0
        detected_inside_expected_pct = 0.0
        expected_coverage_pct = 0.0
        out_of_footprint_pct = 0.0
        spatial_prior_warning: Optional[str] = None

        if expected_mask is not None:
            expected_water_pixels = int(np.sum(expected_mask))
            overlap_water_pixels = int(np.sum(mask & expected_mask))

            if water_pixels > 0:
                detected_inside_expected_pct = (
                    overlap_water_pixels / water_pixels
                ) * 100.0
                out_of_footprint_pct = max(
                    0.0,
                    100.0 - detected_inside_expected_pct,
                )

            if expected_water_pixels > 0:
                expected_coverage_pct = (
                    overlap_water_pixels / expected_water_pixels
                ) * 100.0

            if water_pixels > 500 and detected_inside_expected_pct < 50.0:
                spatial_prior_warning = (
                    "Less than half of detected water pixels overlap the "
                    "stored water-body footprint; review the mask before using "
                    "the observation for baseline/anomaly decisions."
                )

        # Run Guard Constraints
        failures: List[str] = []
        status = "ok"
        is_valid = True

        if water_pixel_pct < self.min_water_pixel_pct:
            failures.append(
                f"Insufficient water pixels: {water_pixel_pct:.2f}% (minimum {self.min_water_pixel_pct}%)"
            )
        elif water_pixel_pct > self.max_water_pixel_pct:
            failures.append(
                f"Abnormally high water coverage: {water_pixel_pct:.2f}% (maximum {self.max_water_pixel_pct}%)"
            )

        if fragmentation_index > self.max_fragmentation_index and water_pixels > 500:
            failures.append(
                f"High fragmentation index: {fragmentation_index:.3f} (max allowed {self.max_fragmentation_index:.3f}; "
                f"largest component occupies only {largest_ratio*100:.1f}% of detected water)"
            )

        if cloud_overlap_pct > self.max_cloud_overlap_pct:
            failures.append(
                f"Excessive cloud/shadow overlap on water body: {cloud_overlap_pct:.2f}% "
                f"(max allowed {self.max_cloud_overlap_pct}%)"
            )
            status = "excessive_cloud_overlap"

        if failures:
            is_valid = False
            if status == "ok":
                status = "low_confidence_mask" if "fragmentation" in str(failures) else "degraded"

        return MaskQualityReport(
            is_valid=is_valid,
            status=status,
            water_pixels=water_pixels,
            total_pixels=total_pixels,
            water_pixel_pct=round(water_pixel_pct, 4),
            water_area_km2=round(water_area_km2, 4),
            num_connected_components=int(num_components),
            largest_component_pixels=largest_pixels,
            largest_component_ratio=round(largest_ratio, 4),
            fragmentation_index=round(fragmentation_index, 4),
            cloud_overlap_pixels=cloud_overlap_pixels,
            cloud_overlap_pct=round(cloud_overlap_pct, 4),
            expected_water_pixels=expected_water_pixels,
            overlap_water_pixels=overlap_water_pixels,
            detected_inside_expected_pct=round(detected_inside_expected_pct, 4),
            expected_coverage_pct=round(expected_coverage_pct, 4),
            out_of_footprint_pct=round(out_of_footprint_pct, 4),
            spatial_prior_warning=spatial_prior_warning,
            failure_reasons=failures,
        )

    def _vectorize_mask_to_geojson(
        self,
        mask: np.ndarray,
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Converts binary mask to clean GeoJSON MultiPolygon in EPSG:4326."""
        transform = profile["transform"]
        src_crs = profile["crs"]

        # Extract vector polygons using rasterio.features.shapes
        shapes_gen = features.shapes(
            mask.astype(np.uint8),
            mask=mask,
            transform=transform,
            connectivity=8,
        )

        polygons: List[Polygon] = []
        for geom, val in shapes_gen:
            if val == 1:
                poly = shape(geom)
                if poly.is_valid and poly.area > 2000.0:  # Ignore microscopic slivers (< 2000 m2)
                    polygons.append(poly)

        if not polygons:
            # Empty collection if no water
            return {
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": []},
                "properties": {"water_body_detected": False, "area_km2": 0.0},
            }

        # Union adjacent polygons
        merged_geom = unary_union(polygons)

        # Reproject from native UTM CRS to EPSG:4326
        native_geojson_geom = mapping(merged_geom)
        reprojected_geom = transform_geom(
            src_crs=src_crs,
            dst_crs="EPSG:4326",
            geom=native_geojson_geom,
        )

        return {
            "type": "Feature",
            "geometry": reprojected_geom,
            "properties": {
                "water_body_detected": True,
                "crs": "EPSG:4326",
            },
        }

    def save_mask_raster(self, result: WaterSegmentationResult, output_filepath: str) -> str:
        """Export binary water mask as a GeoTIFF."""
        path = Path(output_filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(str(path), "w", **result.profile) as dst:
            dst.write(result.water_mask.astype(np.uint8), 1)
            dst.set_band_description(1, "WaterNet_Water_Mask")
        logger.info(f"Saved binary water mask to {path}")
        return str(path)

    def save_boundary_geojson(self, result: WaterSegmentationResult, output_filepath: str) -> str:
        """Export vector boundary as GeoJSON."""
        path = Path(output_filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result.boundary_geojson, f, indent=2)
        logger.info(f"Saved vector boundary GeoJSON to {path}")
        return str(path)

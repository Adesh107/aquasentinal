"""
Sentinel-2 L2A Preprocessing Module.
Handles:
1. Pinned band specification (B02, B03, B04, B08, B11, SCL).
2. Windowed streaming via rasterio from signed Planetary Computer URLs.
3. Reprojection of WGS84 bounding box to native UTM CRS.
4. Harmonization of 20m bands (B11, SCL) to the 10m reference grid.
5. Bottom-Of-Atmosphere (BOA) surface reflectance calibration (scale factor 1/10000 + baseline offset).
6. Export of Analysis-Ready Data (ARD).
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds
from rasterio.enums import Resampling
import rasterio.shutil

from ai.satellite.client import SentinelObservation

logger = logging.getLogger("AquaSentinel.Preprocessor")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [Preprocessor] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# PINNED BAND LIST — KEPT STRICTLY CONSISTENT THROUGH STAGE 5
PINNED_SPECTRAL_BANDS: List[str] = ["B02", "B03", "B04", "B08", "B11"]
ANCILLARY_BANDS: List[str] = ["SCL"]
ALL_ANALYSIS_BANDS: List[str] = PINNED_SPECTRAL_BANDS + ANCILLARY_BANDS

# S2 L2A Calibration constants
S2_SCALE_FACTOR = 10000.0
S2_OFFSET_BASELINE_THRESHOLD = "04.00"
S2_DN_OFFSET = -1000.0  # Introduced in Processing Baseline >= 04.00


@dataclass
class AnalysisReadyData:
    """
    Standard container for calibrated, co-registered analysis-ready bands.
    All spectral bands are float32 in [0.0, 1.0].
    SCL is uint8 categorical mask on the same 10m grid.
    """
    water_body_id: str
    observation_date: str
    satellite_name: str
    cloud_percentage: float
    source_reference: str
    pinned_bands: List[str]
    bands: Dict[str, np.ndarray]  # {"B02": ndarray, "B03": ..., "B04": ..., "B08": ..., "B11": ...}
    scl: Optional[np.ndarray]  # SCL Scene Classification Layer
    profile: Dict[str, Any]  # Rasterio profile (transform, crs, shape)
    height: int
    width: int
    resolution_m: float
    observation_metadata: SentinelObservation


class SentinelPreprocessor:
    """Processes raw Sentinel-2 L2A signed assets into Analysis-Ready Data."""

    def __init__(self, buffer_meters: float = 500.0):
        self.buffer_meters = buffer_meters

    def process(
        self,
        observation: SentinelObservation,
        wgs84_bbox: List[float],
        target_resolution_m: float = 10.0,
    ) -> AnalysisReadyData:
        """
        Extracts, resamples, and calibrates the pinned band list for a water body bounding box.

        Parameters:
            observation: SentinelObservation object from Stage 2.
            wgs84_bbox: [min_lon, min_lat, max_lon, max_lat] in EPSG:4326.
            target_resolution_m: Target grid spacing in meters (10m).

        Returns:
            AnalysisReadyData object containing aligned 10m calibrated float32 arrays.
        """
        logger.info(
            f"Starting preprocessing for {observation.water_body_id} ({observation.source_reference})"
        )
        logger.info(f"Pinned band set: {PINNED_SPECTRAL_BANDS} + {ANCILLARY_BANDS}")

        # Check required bands are present in observation assets
        for b in ALL_ANALYSIS_BANDS:
            if b not in observation.assets:
                raise ValueError(
                    f"Required band '{b}' not found in observation assets for {observation.source_reference}"
                )

        # 1. Establish 10m Reference Grid using B02 (native 10m band)
        b02_url = observation.assets["B02"]
        ref_window, ref_transform, ref_crs, (ref_height, ref_width) = self._get_window_and_transform(
            raster_url=b02_url,
            wgs84_bbox=wgs84_bbox,
            buffer_meters=self.buffer_meters
        )

        logger.info(
            f"Reference 10m grid established: CRS={ref_crs.to_string()}, "
            f"Shape=({ref_height}, {ref_width}) pixels, Window={ref_window}"
        )

        # Determine if baseline offset applies
        apply_offset = self._should_apply_baseline_offset(observation)
        logger.info(f"Radiometric calibration: Scale={S2_SCALE_FACTOR}, BaselineOffset={apply_offset}")

        calibrated_bands: Dict[str, np.ndarray] = {}

        # 2. Read and Calibrate 10m Native Bands (B02, B03, B04, B08)
        native_10m_bands = ["B02", "B03", "B04", "B08"]
        for band_name in native_10m_bands:
            band_url = observation.assets[band_name]
            logger.info(f"Reading and calibrating native 10m band {band_name}...")
            raw_data = self._read_window(band_url, ref_window, out_shape=(ref_height, ref_width))
            calibrated = self._calibrate_dn_to_reflectance(raw_data, apply_offset=apply_offset)
            calibrated_bands[band_name] = calibrated

        # 3. Read and Resample 20m Pinned Band (B11 - SWIR) to 10m Grid
        b11_url = observation.assets["B11"]
        logger.info("Reading and resynthesizing 20m B11 (SWIR) to 10m reference grid via bilinear resampling...")
        b11_raw = self._read_resampled_window(
            band_url=b11_url,
            target_crs=ref_crs,
            target_transform=ref_transform,
            target_shape=(ref_height, ref_width),
            resampling_method=Resampling.bilinear
        )
        b11_calibrated = self._calibrate_dn_to_reflectance(b11_raw, apply_offset=apply_offset)
        calibrated_bands["B11"] = b11_calibrated

        # 4. Read and Resample 20m SCL (Scene Classification Layer) to 10m Grid
        scl_data: Optional[np.ndarray] = None
        if "SCL" in observation.assets:
            scl_url = observation.assets["SCL"]
            logger.info("Reading and resampling 20m SCL to 10m reference grid via nearest-neighbor...")
            scl_raw = self._read_resampled_window(
                band_url=scl_url,
                target_crs=ref_crs,
                target_transform=ref_transform,
                target_shape=(ref_height, ref_width),
                resampling_method=Resampling.nearest
            )
            scl_data = scl_raw.astype(np.uint8)

        # 5. Create GeoTIFF metadata profile
        ard_profile = {
            "driver": "GTiff",
            "height": ref_height,
            "width": ref_width,
            "count": len(PINNED_SPECTRAL_BANDS),
            "dtype": "float32",
            "crs": ref_crs,
            "transform": ref_transform,
            "nodata": np.nan,
            "compress": "lzw",
        }

        logger.info("Preprocessing complete: All analysis-ready bands co-registered to 10m grid.")

        return AnalysisReadyData(
            water_body_id=observation.water_body_id,
            observation_date=observation.observation_date,
            satellite_name=observation.satellite_name,
            cloud_percentage=observation.cloud_percentage,
            source_reference=observation.source_reference,
            pinned_bands=PINNED_SPECTRAL_BANDS,
            bands=calibrated_bands,
            scl=scl_data,
            profile=ard_profile,
            height=ref_height,
            width=ref_width,
            resolution_m=target_resolution_m,
            observation_metadata=observation,
        )

    def _get_window_and_transform(
        self,
        raster_url: str,
        wgs84_bbox: List[float],
        buffer_meters: float,
    ) -> Tuple[rasterio.windows.Window, rasterio.Affine, Any, Tuple[int, int]]:
        """Calculate pixel window and affine transform for bounding box in native CRS."""
        with rasterio.open(raster_url) as src:
            src_crs = src.crs
            # Reproject WGS84 bbox [min_lon, min_lat, max_lon, max_lat] to native UTM
            min_x, min_y, max_x, max_y = transform_bounds(
                "EPSG:4326", src_crs, *wgs84_bbox
            )
            # Add spatial buffer
            min_x -= buffer_meters
            min_y -= buffer_meters
            max_x += buffer_meters
            max_y += buffer_meters

            # Compute window
            window = from_bounds(min_x, min_y, max_x, max_y, transform=src.transform)
            # Round window to full integer pixels
            window = window.round_offsets().round_lengths()

            # Ensure window is inside bounds
            max_w = src.width
            max_h = src.height
            col_off = max(0, int(window.col_off))
            row_off = max(0, int(window.row_off))
            width = min(max_w - col_off, int(window.width))
            height = min(max_h - row_off, int(window.height))
            bounded_window = rasterio.windows.Window(col_off, row_off, width, height)

            # Window affine transform
            win_transform = rasterio.windows.transform(bounded_window, src.transform)
            return bounded_window, win_transform, src_crs, (height, width)

    def _read_window(
        self,
        raster_url: str,
        window: rasterio.windows.Window,
        out_shape: Tuple[int, int]
    ) -> np.ndarray:
        """Stream a specific window from raster URL."""
        with rasterio.open(raster_url) as src:
            data = src.read(1, window=window, out_shape=out_shape, resampling=Resampling.bilinear)
            return data.astype(np.float32)

    def _read_resampled_window(
        self,
        band_url: str,
        target_crs: Any,
        target_transform: rasterio.Affine,
        target_shape: Tuple[int, int],
        resampling_method: Resampling,
    ) -> np.ndarray:
        """
        Read from a raster URL (e.g. 20m B11 or SCL) and warp/resample onto the exact 10m target grid.
        """
        destination = np.zeros(target_shape, dtype=np.float32)
        with rasterio.open(band_url) as src:
            rasterio.warp.reproject(
                source=rasterio.band(src, 1),
                destination=destination,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=target_transform,
                dst_crs=target_crs,
                resampling=resampling_method,
            )
        return destination

    def _should_apply_baseline_offset(self, obs: SentinelObservation) -> bool:
        """Check if ESA Processing Baseline >= 04.00 requires BOA offset adjustment."""
        baseline = obs.quality_info.processing_baseline
        if baseline:
            try:
                base_float = float(baseline)
                return base_float >= 4.0
            except ValueError:
                return baseline >= S2_OFFSET_BASELINE_THRESHOLD
        # If observation is from 2022 or later, default to true
        if obs.observation_date >= "2022-01-25":
            return True
        return False

    def _calibrate_dn_to_reflectance(self, raw_dn: np.ndarray, apply_offset: bool) -> np.ndarray:
        """
        Converts raw Digital Numbers (DN) to BOA surface reflectance in [0.0, 1.0].
        Nodata (0) is converted to NaN.
        """
        # Create output array
        reflectance = np.full_like(raw_dn, np.nan, dtype=np.float32)
        valid_mask = raw_dn > 0

        if not np.any(valid_mask):
            return reflectance

        if apply_offset:
            # Baseline >= 04.00: Reflectance = (DN + (-1000)) / 10000.0
            cal = (raw_dn[valid_mask] + S2_DN_OFFSET) / S2_SCALE_FACTOR
        else:
            # Baseline < 04.00: Reflectance = DN / 10000.0
            cal = raw_dn[valid_mask] / S2_SCALE_FACTOR

        # Reflectance clipping to physical bounds [0.0, 1.0]
        cal = np.clip(cal, 0.0, 1.0)
        reflectance[valid_mask] = cal
        return reflectance

    def save_ard_geotiff(self, ard: AnalysisReadyData, output_filepath: str) -> str:
        """Save analysis-ready bands as a multi-band GeoTIFF."""
        path = Path(output_filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        profile = ard.profile.copy()
        profile.update(count=len(PINNED_SPECTRAL_BANDS))

        with rasterio.open(str(path), "w", **profile) as dst:
            for idx, band_name in enumerate(PINNED_SPECTRAL_BANDS, 1):
                dst.write(ard.bands[band_name], idx)
                dst.set_band_description(idx, band_name)

        logger.info(f"Saved Analysis-Ready Data stack to {path}")
        return str(path)

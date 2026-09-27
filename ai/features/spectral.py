"""
Spectral Feature Extraction Module.
Computes turbidity, chlorophyll, and algal spectral indices from the pinned
band set (B02, B03, B04, B08, B11) strictly within the validated water mask.

OUTPUT CONTRACT:
{
    "turbidity_features": { ... },
    "chlorophyll_features": { ... },
    "algal_features": { ... }
}

SCIENTIFIC HONESTY:
- All indicators are normalized to a documented [0.0, 1.0] range.
- No fabricated physical units (NTU, µg/L) are ever output.
- Each indicator's normalization formula and input bands are documented inline.
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict

import numpy as np

from ai.preprocessing.preprocessor import AnalysisReadyData
from ai.segmentation.waternet import WaterSegmentationResult

logger = logging.getLogger("AquaSentinel.SpectralFeatures")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [SpectralFeatures] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Division with zero-denominator protection; returns NaN where denominator ~ 0."""
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(np.abs(denominator) > 1e-8, numerator / denominator, np.nan)
    return result.astype(np.float32)


def _normalize_index(arr: np.ndarray, src_min: float, src_max: float) -> np.ndarray:
    """Linearly maps [src_min, src_max] → [0.0, 1.0] and clips."""
    span = src_max - src_min
    if span < 1e-10:
        return np.full_like(arr, 0.5, dtype=np.float32)
    normalized = (arr - src_min) / span
    return np.clip(normalized, 0.0, 1.0).astype(np.float32)


def _masked_stats(values: np.ndarray) -> Dict[str, float]:
    """Compute summary statistics on valid (non-NaN) values."""
    valid = values[~np.isnan(values)]
    if len(valid) == 0:
        return {"mean": float("nan"), "median": float("nan"), "std": float("nan"),
                "min": float("nan"), "max": float("nan"), "p10": float("nan"),
                "p90": float("nan"), "valid_pixels": 0}
    return {
        "mean": round(float(np.mean(valid)), 6),
        "median": round(float(np.median(valid)), 6),
        "std": round(float(np.std(valid)), 6),
        "min": round(float(np.min(valid)), 6),
        "max": round(float(np.max(valid)), 6),
        "p10": round(float(np.percentile(valid, 10)), 6),
        "p90": round(float(np.percentile(valid, 90)), 6),
        "valid_pixels": int(len(valid)),
    }


@dataclass
class SpectralFeatures:
    """Container for computed spectral feature sets."""
    water_body_id: str
    observation_date: str
    source_reference: str
    water_area_km2: float
    turbidity_features: Dict[str, Any]
    chlorophyll_features: Dict[str, Any]
    algal_features: Dict[str, Any]
    # Aggregated single-value indicators (documented [0.0, 1.0])
    turbidity_indicator: float
    chlorophyll_indicator: float
    algal_indicator: float
    # Internal per-pixel composites used by spatial anomaly localization.
    # Kept out of to_dict() so the public indicator contract remains unchanged.
    spatial_maps: Dict[str, np.ndarray] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
            if key != "spatial_maps"
        }


class SpectralFeatureExtractor:
    """
    Extracts water-quality-related spectral indices from within the water mask.
    All outputs are normalized indicators — never fabricated physical units.
    """

    # Normalization boundaries for each raw index.
    # These are empirically derived from Sentinel-2 literature and represent
    # the expected range of index values over inland water bodies.
    # They are NOT ground-truth calibrations.
    NDTI_RANGE = (-0.30, 0.40)     # Normalized Difference Turbidity Index
    RED_GREEN_RANGE = (0.3, 2.0)   # Red / Green reflectance ratio
    B04_RANGE = (0.0, 0.15)        # Red-band absolute reflectance over water
    NDCI_RANGE = (-0.40, 0.30)     # Normalized Difference Chlorophyll Index
    GREEN_BLUE_RANGE = (0.5, 2.5)  # Green / Blue reflectance ratio
    NIR_RED_RANGE = (-0.50, 0.30)  # (NIR - Red) / (NIR + Red)
    FAI_RANGE = (-0.02, 0.08)      # Floating Algae Index
    NIR_ABS_RANGE = (0.0, 0.10)    # NIR absolute reflectance over water
    MNDWI_INV_RANGE = (-0.50, 0.30)  # Inverted MNDWI for algal sensitivity

    def extract(
        self,
        ard: AnalysisReadyData,
        segmentation: WaterSegmentationResult,
    ) -> SpectralFeatures:
        """
        Extract spectral features from the pinned bands within the water mask.

        Parameters:
            ard: Analysis-ready data from Stage 3 (calibrated float32 bands).
            segmentation: WaterNet segmentation result from Stage 4 (binary mask).

        Returns:
            SpectralFeatures with turbidity, chlorophyll, and algal feature dictionaries.
        """
        logger.info(f"Extracting spectral features for {ard.water_body_id} within water mask...")

        water_mask = segmentation.water_mask
        b02 = ard.bands["B02"]  # Blue
        b03 = ard.bands["B03"]  # Green
        b04 = ard.bands["B04"]  # Red
        b08 = ard.bands["B08"]  # NIR
        b11 = ard.bands["B11"]  # SWIR-1

        # Apply water mask: set non-water pixels to NaN
        def mask_band(band: np.ndarray) -> np.ndarray:
            masked = band.copy()
            masked[~water_mask] = np.nan
            return masked

        b02_w = mask_band(b02)
        b03_w = mask_band(b03)
        b04_w = mask_band(b04)
        b08_w = mask_band(b08)
        b11_w = mask_band(b11)

        # ── TURBIDITY FEATURES ──────────────────────────────────────────
        # 1. NDTI = (Red - Green) / (Red + Green)
        #    Higher NDTI → more suspended sediments → more turbid.
        ndti = _safe_ratio(b04_w - b03_w, b04_w + b03_w)
        ndti_norm = _normalize_index(ndti, *self.NDTI_RANGE)

        # 2. Red / Green ratio
        #    Turbid water has elevated red reflectance relative to green.
        red_green_ratio = _safe_ratio(b04_w, b03_w)
        rg_norm = _normalize_index(red_green_ratio, *self.RED_GREEN_RANGE)

        # 3. B04 (Red) absolute reflectance
        #    Directly correlated with suspended sediment concentration.
        b04_norm = _normalize_index(b04_w, *self.B04_RANGE)

        # Composite turbidity indicator: weighted blend
        turb_composite = 0.45 * ndti_norm + 0.30 * rg_norm + 0.25 * b04_norm
        turbidity_indicator = float(np.nanmean(turb_composite))
        turbidity_indicator = round(max(0.0, min(1.0, turbidity_indicator)), 6)

        turbidity_features = {
            "ndti_index": _masked_stats(ndti),
            "ndti_normalized": _masked_stats(ndti_norm),
            "red_green_ratio": _masked_stats(red_green_ratio),
            "red_green_normalized": _masked_stats(rg_norm),
            "red_reflectance": _masked_stats(b04_w),
            "red_reflectance_normalized": _masked_stats(b04_norm),
            "composite_turbidity_indicator": _masked_stats(turb_composite),
            "turbidity_indicator": turbidity_indicator,
            "normalization_doc": {
                "method": "Linear blend of NDTI, Red/Green ratio, Red reflectance",
                "weights": {"ndti": 0.45, "red_green": 0.30, "red_refl": 0.25},
                "ndti_range": list(self.NDTI_RANGE),
                "red_green_range": list(self.RED_GREEN_RANGE),
                "red_refl_range": list(self.B04_RANGE),
                "output_range": [0.0, 1.0],
                "warning": "Indicator only. Not calibrated to physical units without ground truth.",
            },
        }

        logger.info(f"  Turbidity indicator: {turbidity_indicator:.4f}")

        # ── CHLOROPHYLL FEATURES ────────────────────────────────────────
        # 1. NDCI-like = (NIR - Red) / (NIR + Red)
        #    Chlorophyll absorption in red, reflectance plateau in NIR.
        ndci = _safe_ratio(b08_w - b04_w, b08_w + b04_w)
        ndci_norm = _normalize_index(ndci, *self.NDCI_RANGE)

        # 2. Green / Blue ratio
        #    Elevated in productive (chlorophyll-rich) waters.
        green_blue_ratio = _safe_ratio(b03_w, b02_w)
        gb_norm = _normalize_index(green_blue_ratio, *self.GREEN_BLUE_RANGE)

        # 3. NIR / Red normalized difference (vegetation-like response in water)
        nir_red_nd = _safe_ratio(b08_w - b04_w, b08_w + b04_w)
        nr_norm = _normalize_index(nir_red_nd, *self.NIR_RED_RANGE)

        # Composite chlorophyll indicator
        chl_composite = 0.40 * ndci_norm + 0.35 * gb_norm + 0.25 * nr_norm
        chlorophyll_indicator = float(np.nanmean(chl_composite))
        chlorophyll_indicator = round(max(0.0, min(1.0, chlorophyll_indicator)), 6)

        chlorophyll_features = {
            "ndci_index": _masked_stats(ndci),
            "ndci_normalized": _masked_stats(ndci_norm),
            "green_blue_ratio": _masked_stats(green_blue_ratio),
            "green_blue_normalized": _masked_stats(gb_norm),
            "nir_red_nd": _masked_stats(nir_red_nd),
            "nir_red_normalized": _masked_stats(nr_norm),
            "composite_chlorophyll_indicator": _masked_stats(chl_composite),
            "chlorophyll_indicator": chlorophyll_indicator,
            "normalization_doc": {
                "method": "Linear blend of NDCI, Green/Blue ratio, NIR-Red ND",
                "weights": {"ndci": 0.40, "green_blue": 0.35, "nir_red_nd": 0.25},
                "ndci_range": list(self.NDCI_RANGE),
                "green_blue_range": list(self.GREEN_BLUE_RANGE),
                "nir_red_range": list(self.NIR_RED_RANGE),
                "output_range": [0.0, 1.0],
                "warning": "Indicator only. Not calibrated to physical units without ground truth.",
            },
        }

        logger.info(f"  Chlorophyll indicator: {chlorophyll_indicator:.4f}")

        # ── ALGAL FEATURES ──────────────────────────────────────────────
        # 1. Floating Algae Index (FAI)
        #    FAI = NIR - (Red + (SWIR - Red) * (λ_NIR - λ_Red) / (λ_SWIR - λ_Red))
        #    Using wavelengths: Red=665nm, NIR=842nm, SWIR=1610nm
        lambda_red = 665.0
        lambda_nir = 842.0
        lambda_swir = 1610.0
        fai_baseline = b04_w + (b11_w - b04_w) * ((lambda_nir - lambda_red) / (lambda_swir - lambda_red))
        fai = b08_w - fai_baseline
        fai_norm = _normalize_index(fai, *self.FAI_RANGE)

        # 2. NIR absolute reflectance over water
        #    Elevated NIR can indicate surface algal scum/floating vegetation.
        nir_abs_norm = _normalize_index(b08_w, *self.NIR_ABS_RANGE)

        # 3. Inverted MNDWI sensitivity
        #    Lower MNDWI over water may indicate surface algal interference.
        mndwi = _safe_ratio(b03_w - b11_w, b03_w + b11_w)
        mndwi_inv = -mndwi  # Invert: higher = more algal interference
        mndwi_inv_norm = _normalize_index(mndwi_inv, *self.MNDWI_INV_RANGE)

        # Composite algal indicator
        alg_composite = 0.50 * fai_norm + 0.30 * nir_abs_norm + 0.20 * mndwi_inv_norm
        algal_indicator = float(np.nanmean(alg_composite))
        algal_indicator = round(max(0.0, min(1.0, algal_indicator)), 6)

        algal_features = {
            "fai_index": _masked_stats(fai),
            "fai_normalized": _masked_stats(fai_norm),
            "nir_absolute": _masked_stats(b08_w),
            "nir_absolute_normalized": _masked_stats(nir_abs_norm),
            "mndwi_inverted": _masked_stats(mndwi_inv),
            "mndwi_inverted_normalized": _masked_stats(mndwi_inv_norm),
            "composite_algal_indicator": _masked_stats(alg_composite),
            "algal_indicator": algal_indicator,
            "normalization_doc": {
                "method": "Linear blend of FAI, NIR absolute, Inverted MNDWI",
                "weights": {"fai": 0.50, "nir_abs": 0.30, "mndwi_inv": 0.20},
                "fai_range": list(self.FAI_RANGE),
                "nir_abs_range": list(self.NIR_ABS_RANGE),
                "mndwi_inv_range": list(self.MNDWI_INV_RANGE),
                "output_range": [0.0, 1.0],
                "warning": "Indicator only. Not calibrated to physical units without ground truth.",
            },
        }

        logger.info(f"  Algal indicator: {algal_indicator:.4f}")
        logger.info("Spectral feature extraction complete.")

        return SpectralFeatures(
            water_body_id=ard.water_body_id,
            observation_date=ard.observation_date,
            source_reference=ard.source_reference,
            water_area_km2=segmentation.water_area_km2,
            turbidity_features=turbidity_features,
            chlorophyll_features=chlorophyll_features,
            algal_features=algal_features,
            turbidity_indicator=turbidity_indicator,
            chlorophyll_indicator=chlorophyll_indicator,
            algal_indicator=algal_indicator,
            spatial_maps={
                "turbidity": turb_composite,
                "chlorophyll": chl_composite,
                "algal": alg_composite,
            },
        )

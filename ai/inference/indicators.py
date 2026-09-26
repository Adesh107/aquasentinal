"""
Inference Module for Water Quality Indicators.
Produces final indicator values for a given observation.

Operates in two modes:
1. INDICATOR-ONLY MODE (default / prototype): Uses spectral feature composites
   directly from Stage 5. No ML model is applied. Status = "prototype_indicator_only".
2. MODEL-CALIBRATED MODE: If a promoted ML model exists (trained with real ground
   truth in Stage 6), applies the model to spectral features for refined predictions.
   Status = "ok" or "degraded" depending on model coverage.

GUARD: Never fabricates physical units or accuracy claims. Mode is always
explicitly communicated through the status field.
"""

import logging
import pickle
import json
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("AquaSentinel.Inference.Indicators")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [Indicators] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

SAVED_MODELS_DIR = Path("ai/models/saved_models")
MODEL_MANIFEST_FILE = SAVED_MODELS_DIR / "model_manifest.json"


@dataclass
class WaterQualityIndicators:
    """Final water quality indicator output for a single observation."""
    water_body_id: str
    observation_date: str
    source_reference: str
    water_area_km2: float

    # Indicators (always [0.0, 1.0])
    turbidity_indicator: float
    chlorophyll_indicator: float
    algal_indicator: float

    # System status
    mode: str  # "prototype_indicator_only" or "model_calibrated"
    model_version: Optional[str]
    processing_version: str

    # Per-target calibration status
    calibration_status: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IndicatorEngine:
    """
    Produces water quality indicators from spectral features.
    Automatically detects whether trained models are available.
    """

    PROCESSING_VERSION = "0.1.0"

    def __init__(self):
        self._models: Dict[str, Any] = {}
        self._manifest: Optional[Dict[str, Any]] = None
        self._mode = "prototype_indicator_only"
        self._model_version: Optional[str] = None
        self._load_models()

    def _load_models(self):
        """Attempt to load promoted models from disk."""
        if not MODEL_MANIFEST_FILE.exists():
            logger.info(
                "[Indicators] No model manifest found. Operating in indicator-only / prototype mode."
            )
            return

        with open(MODEL_MANIFEST_FILE, "r", encoding="utf-8") as f:
            self._manifest = json.load(f)

        self._model_version = self._manifest.get("model_version")
        model_entries = self._manifest.get("models", {})

        loaded_count = 0
        for target_name, meta in model_entries.items():
            if not meta.get("promoted", False):
                logger.info(f"[Indicators] Model for '{target_name}' not promoted. Skipping.")
                continue

            model_path = SAVED_MODELS_DIR / meta["file"]
            if not model_path.exists():
                logger.warning(f"[Indicators] Model file missing: {model_path}")
                continue

            with open(model_path, "rb") as f:
                self._models[target_name] = pickle.load(f)
            loaded_count += 1
            logger.info(
                f"[Indicators] Loaded promoted model for '{target_name}' "
                f"(R^2={meta['cv_r2_mean']:.4f})"
            )

        if loaded_count > 0:
            self._mode = "model_calibrated"
            logger.info(f"[Indicators] Operating in MODEL-CALIBRATED mode ({loaded_count} models loaded).")
        else:
            logger.info("[Indicators] No promoted models loaded. Operating in indicator-only mode.")

    def compute(self, spectral_features_dict: Dict[str, Any]) -> WaterQualityIndicators:
        """
        Compute final water quality indicators.

        In indicator-only mode: returns spectral composite indicators directly.
        In model-calibrated mode: applies trained ML models to spectral features.
        """
        water_body_id = spectral_features_dict.get("water_body_id", "unknown")
        observation_date = spectral_features_dict.get("observation_date", "unknown")
        source_reference = spectral_features_dict.get("source_reference", "unknown")
        water_area_km2 = spectral_features_dict.get("water_area_km2", 0.0)

        # Default: use spectral composite indicators from Stage 5
        turbidity = spectral_features_dict.get("turbidity_indicator", 0.0)
        chlorophyll = spectral_features_dict.get("chlorophyll_indicator", 0.0)
        algal = spectral_features_dict.get("algal_indicator", 0.0)

        calibration_status = {
            "turbidity": "spectral_indicator_only",
            "chlorophyll": "spectral_indicator_only",
            "algal": "spectral_indicator_only",
        }

        # If models are available, apply them
        if self._mode == "model_calibrated":
            from ai.training.prepare_dataset import extract_feature_vector, FEATURE_COLUMNS
            import numpy as np

            fv = extract_feature_vector(spectral_features_dict)
            X = np.array([[fv[col] for col in FEATURE_COLUMNS]], dtype=np.float32)

            target_to_indicator = {
                "turbidity_measured": "turbidity",
                "chlorophyll_measured": "chlorophyll",
                "algal_density_measured": "algal",
            }

            for target_name, indicator_key in target_to_indicator.items():
                if target_name in self._models:
                    pred = float(self._models[target_name].predict(X)[0])
                    pred = max(0.0, min(1.0, pred))  # Clip to [0, 1]

                    if indicator_key == "turbidity":
                        turbidity = pred
                    elif indicator_key == "chlorophyll":
                        chlorophyll = pred
                    elif indicator_key == "algal":
                        algal = pred

                    calibration_status[indicator_key] = "model_calibrated"
                    logger.info(
                        f"[Indicators] Model prediction for '{indicator_key}': {pred:.4f}"
                    )

        logger.info(
            f"[Indicators] Final indicators for {water_body_id}: "
            f"Turb={turbidity:.4f}, Chl={chlorophyll:.4f}, Alg={algal:.4f} "
            f"(mode={self._mode})"
        )

        return WaterQualityIndicators(
            water_body_id=water_body_id,
            observation_date=observation_date,
            source_reference=source_reference,
            water_area_km2=water_area_km2,
            turbidity_indicator=round(turbidity, 6),
            chlorophyll_indicator=round(chlorophyll, 6),
            algal_indicator=round(algal, 6),
            mode=self._mode,
            model_version=self._model_version,
            processing_version=self.PROCESSING_VERSION,
            calibration_status=calibration_status,
        )

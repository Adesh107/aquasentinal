"""
Dataset Preparation for Water Quality ML Models.
Converts paired (spectral_features, ground_truth_measurements) into
scikit-learn-ready feature matrices and target vectors.

GUARD: This module NEVER fabricates training data or ground truth.
If no ground truth files exist, it reports the gap clearly and returns None.
"""

import logging
import json
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import numpy as np
import pandas as pd

logger = logging.getLogger("AquaSentinel.Training.PrepareDataset")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [PrepareDataset] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Feature columns extracted from SpectralFeatures for ML input
FEATURE_COLUMNS = [
    # Turbidity sub-features
    "ndti_mean", "ndti_median", "ndti_std", "ndti_p10", "ndti_p90",
    "red_green_ratio_mean", "red_reflectance_mean",
    # Chlorophyll sub-features
    "ndci_mean", "ndci_median", "ndci_std", "ndci_p10", "ndci_p90",
    "green_blue_ratio_mean",
    # Algal sub-features
    "fai_mean", "fai_median", "fai_std", "fai_p10", "fai_p90",
    "nir_absolute_mean",
]

# Target columns (ground truth measurements, when available)
TARGET_COLUMNS = [
    "turbidity_measured",      # True turbidity (e.g. NTU from field sensor)
    "chlorophyll_measured",    # True chlorophyll-a (e.g. ug/L from lab)
    "algal_density_measured",  # True algal cell count or biomass index
]

GROUND_TRUTH_DIR = Path("ai/training/ground_truth")


def extract_feature_vector(spectral_features_dict: Dict[str, Any]) -> Dict[str, float]:
    """
    Extracts a flat feature vector from a SpectralFeatures dictionary.
    Returns a dict suitable for one row of a DataFrame.
    """
    tf = spectral_features_dict.get("turbidity_features", {})
    cf = spectral_features_dict.get("chlorophyll_features", {})
    af = spectral_features_dict.get("algal_features", {})

    def _get(feature_dict: dict, key: str, stat: str, default: float = 0.0) -> float:
        sub = feature_dict.get(key, {})
        return float(sub.get(stat, default))

    return {
        "ndti_mean": _get(tf, "ndti_index", "mean"),
        "ndti_median": _get(tf, "ndti_index", "median"),
        "ndti_std": _get(tf, "ndti_index", "std"),
        "ndti_p10": _get(tf, "ndti_index", "p10"),
        "ndti_p90": _get(tf, "ndti_index", "p90"),
        "red_green_ratio_mean": _get(tf, "red_green_ratio", "mean"),
        "red_reflectance_mean": _get(tf, "red_reflectance", "mean"),
        "ndci_mean": _get(cf, "ndci_index", "mean"),
        "ndci_median": _get(cf, "ndci_index", "median"),
        "ndci_std": _get(cf, "ndci_index", "std"),
        "ndci_p10": _get(cf, "ndci_index", "p10"),
        "ndci_p90": _get(cf, "ndci_index", "p90"),
        "green_blue_ratio_mean": _get(cf, "green_blue_ratio", "mean"),
        "fai_mean": _get(af, "fai_index", "mean"),
        "fai_median": _get(af, "fai_index", "median"),
        "fai_std": _get(af, "fai_index", "std"),
        "fai_p10": _get(af, "fai_index", "p10"),
        "fai_p90": _get(af, "fai_index", "p90"),
        "nir_absolute_mean": _get(af, "nir_absolute", "mean"),
    }


def load_ground_truth() -> Optional[pd.DataFrame]:
    """
    Loads ground truth CSV files from ai/training/ground_truth/.
    Expected format: CSV with columns including water_body_id, observation_date,
    and one or more of TARGET_COLUMNS.

    GUARD: Returns None if no ground truth data exists. Never fabricates data.
    """
    if not GROUND_TRUTH_DIR.exists():
        logger.warning(
            f"[GUARD] Ground truth directory does not exist: {GROUND_TRUTH_DIR}. "
            "No training data available. System will operate in indicator-only mode."
        )
        return None

    csv_files = list(GROUND_TRUTH_DIR.glob("*.csv"))
    if not csv_files:
        logger.warning(
            f"[GUARD] No ground truth CSV files found in {GROUND_TRUTH_DIR}. "
            "No training data available. System will operate in indicator-only mode."
        )
        return None

    dfs = []
    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path)
            dfs.append(df)
            logger.info(f"Loaded ground truth file: {csv_path} ({len(df)} records)")
        except Exception as e:
            logger.error(f"Failed to load {csv_path}: {e}")

    if not dfs:
        return None

    combined = pd.concat(dfs, ignore_index=True)
    logger.info(f"Total ground truth records: {len(combined)}")
    return combined


def prepare_dataset(
    spectral_features_list: List[Dict[str, Any]],
    ground_truth_df: Optional[pd.DataFrame] = None,
) -> Optional[Tuple[np.ndarray, np.ndarray, List[str], List[str]]]:
    """
    Pairs spectral features with ground truth measurements.

    Returns:
        (X, y, feature_names, target_names) if sufficient paired data exists.
        None if ground truth is unavailable or insufficient.

    GUARD: Never fabricates training pairs. Returns None with clear logging
    if data is unavailable.
    """
    if ground_truth_df is None:
        logger.warning(
            "[GUARD] No ground truth data provided. Cannot prepare training dataset. "
            "The system will remain in indicator-only / prototype mode."
        )
        return None

    # Extract feature vectors
    feature_rows = []
    for sf in spectral_features_list:
        fv = extract_feature_vector(sf)
        fv["water_body_id"] = sf.get("water_body_id", "")
        fv["observation_date"] = sf.get("observation_date", "")
        feature_rows.append(fv)

    features_df = pd.DataFrame(feature_rows)

    # Merge on water_body_id + observation_date
    merged = features_df.merge(
        ground_truth_df,
        on=["water_body_id", "observation_date"],
        how="inner",
    )

    if len(merged) < 10:
        logger.warning(
            f"[GUARD] Insufficient paired observations ({len(merged)} < 10 minimum). "
            "Cannot train a reliable model. System remains in indicator-only mode."
        )
        return None

    # Extract X and y
    available_targets = [t for t in TARGET_COLUMNS if t in merged.columns]
    if not available_targets:
        logger.warning(
            "[GUARD] Ground truth file does not contain any recognized target columns "
            f"({TARGET_COLUMNS}). Cannot prepare training dataset."
        )
        return None

    X = merged[FEATURE_COLUMNS].values.astype(np.float32)
    y = merged[available_targets].values.astype(np.float32)

    # Check for NaN contamination
    valid_rows = ~(np.isnan(X).any(axis=1) | np.isnan(y).any(axis=1))
    X = X[valid_rows]
    y = y[valid_rows]

    if len(X) < 10:
        logger.warning(
            f"[GUARD] After NaN filtering, only {len(X)} valid rows remain (< 10 minimum). "
            "Cannot train a reliable model."
        )
        return None

    logger.info(
        f"Prepared training dataset: {X.shape[0]} samples, "
        f"{X.shape[1]} features, {y.shape[1]} targets ({available_targets})"
    )
    return X, y, FEATURE_COLUMNS, available_targets

"""
Historical Baseline Module.
Stores and manages multiple observations per water_body_id, computes
running statistical baselines, and enforces the minimum-observation guard.

Each observation record preserves: date, water_area, indicators, quality info,
and anomaly info (when available from Stage 8).

GUARD: A baseline is only considered valid when >= MIN_OBSERVATIONS prior
observations exist. Below that, the baseline status is 'insufficient' and
no statistical comparison is performed against noise.
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

import numpy as np

logger = logging.getLogger("AquaSentinel.Baseline")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [Baseline] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

BASELINE_STORE_DIR = Path("ai/outputs/json/baselines")
MIN_OBSERVATIONS = 3  # Minimum prior observations required for a valid baseline


@dataclass
class ObservationRecord:
    """A single historical observation for a water body."""
    water_body_id: str
    observation_date: str
    source_reference: str
    water_area_km2: float
    turbidity_indicator: float
    chlorophyll_indicator: float
    algal_indicator: float
    cloud_percentage: float
    mask_quality_status: str  # "ok", "degraded", etc.
    mode: str  # "prototype_indicator_only" or "model_calibrated"
    anomaly_score: Optional[float] = None
    anomaly_level: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BaselineStatistics:
    """Running statistical summary for a water body's historical observations."""
    water_body_id: str
    num_observations: int
    status: str  # "valid", "insufficient"
    date_range: Dict[str, str]  # {"earliest": ..., "latest": ...}

    # Per-indicator statistics (only populated when status == "valid")
    water_area_stats: Dict[str, float] = field(default_factory=dict)
    turbidity_stats: Dict[str, float] = field(default_factory=dict)
    chlorophyll_stats: Dict[str, float] = field(default_factory=dict)
    algal_stats: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HistoricalBaseline:
    """
    Manages observation history and baseline computation per water body.
    Persists records as JSON files in ai/outputs/json/baselines/.
    """

    def __init__(self, store_dir: Path = BASELINE_STORE_DIR):
        self.store_dir = store_dir
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._histories: Dict[str, List[ObservationRecord]] = {}

    def _history_filepath(self, water_body_id: str) -> Path:
        safe_id = water_body_id.replace("/", "_").replace("\\", "_")
        return self.store_dir / f"{safe_id}_history.json"

    def load_history(self, water_body_id: str) -> List[ObservationRecord]:
        """Load observation history from disk."""
        if water_body_id in self._histories:
            return self._histories[water_body_id]

        filepath = self._history_filepath(water_body_id)
        if not filepath.exists():
            logger.info(f"No prior history found for '{water_body_id}'. Starting fresh.")
            self._histories[water_body_id] = []
            return []

        with open(filepath, "r", encoding="utf-8") as f:
            raw_records = json.load(f)

        records = []
        for r in raw_records:
            records.append(ObservationRecord(**r))

        self._histories[water_body_id] = records
        logger.info(f"Loaded {len(records)} historical observations for '{water_body_id}'.")
        return records

    def save_history(self, water_body_id: str) -> str:
        """Persist observation history to disk."""
        records = self._histories.get(water_body_id, [])
        filepath = self._history_filepath(water_body_id)

        serialized = [r.to_dict() for r in records]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2)

        logger.info(f"Saved {len(records)} observations for '{water_body_id}' to {filepath}.")
        return str(filepath)

    def add_observation(self, record: ObservationRecord) -> int:
        """
        Add an observation to the history. Deduplicates by (water_body_id, observation_date).
        Returns the new total count.
        """
        wbid = record.water_body_id
        if wbid not in self._histories:
            self.load_history(wbid)

        history = self._histories[wbid]

        # Deduplicate: replace if same date exists
        existing_idx = None
        for i, existing in enumerate(history):
            if existing.observation_date == record.observation_date:
                existing_idx = i
                break

        if existing_idx is not None:
            history[existing_idx] = record
            logger.info(
                f"Updated existing observation for '{wbid}' on {record.observation_date}."
            )
        else:
            history.append(record)
            logger.info(
                f"Added new observation for '{wbid}' on {record.observation_date}. "
                f"Total: {len(history)}."
            )

        # Sort by date
        history.sort(key=lambda r: r.observation_date)
        self._histories[wbid] = history

        # Auto-persist
        self.save_history(wbid)
        return len(history)

    def compute_baseline(self, water_body_id: str) -> BaselineStatistics:
        """
        Compute running statistical baseline for a water body.

        GUARD: If fewer than MIN_OBSERVATIONS exist, returns status='insufficient'
        and does not compute statistics against noise.
        """
        if water_body_id not in self._histories:
            self.load_history(water_body_id)

        history = self._histories.get(water_body_id, [])

        # Only observations whose water mask passed the segmentation quality
        # guard are eligible to define a statistical baseline. Poor masks can
        # still be retained in history for audit/display, but must not become
        # the reference distribution used for anomaly detection.
        # "ok_with_warning" is eligible when the hard mask-quality guard
        # passed. Its warning is retained for audit/UI, but warnings about the
        # stored reference footprint do not invalidate the spectral observation.
        eligible_statuses = {"ok", "ok_with_warning"}
        eligible_history = [
            record
            for record in history
            if record.mask_quality_status in eligible_statuses
        ]
        excluded_count = len(history) - len(eligible_history)
        num_obs = len(eligible_history)

        if excluded_count:
            logger.info(
                f"Excluding {excluded_count} low-quality observations for "
                f"'{water_body_id}' from baseline computation."
            )

        if num_obs == 0:
            logger.info(f"No observations for '{water_body_id}'. Baseline is insufficient.")
            return BaselineStatistics(
                water_body_id=water_body_id,
                num_observations=0,
                status="insufficient",
                date_range={"earliest": "N/A", "latest": "N/A"},
            )

        dates = [r.observation_date for r in eligible_history]
        date_range = {"earliest": min(dates), "latest": max(dates)}

        if num_obs < MIN_OBSERVATIONS:
            logger.warning(
                f"[GUARD] Only {num_obs} observations for '{water_body_id}' "
                f"(minimum {MIN_OBSERVATIONS} required). Baseline marked as 'insufficient'. "
                "No statistical comparison will be performed against noise."
            )
            return BaselineStatistics(
                water_body_id=water_body_id,
                num_observations=num_obs,
                status="insufficient",
                date_range=date_range,
            )

        # Compute statistics across all historical observations
        areas = np.array([r.water_area_km2 for r in eligible_history])
        turbs = np.array([r.turbidity_indicator for r in eligible_history])
        chlors = np.array([r.chlorophyll_indicator for r in eligible_history])
        algals = np.array([r.algal_indicator for r in eligible_history])

        def _compute_stats(values: np.ndarray) -> Dict[str, float]:
            return {
                "mean": round(float(np.mean(values)), 6),
                "std": round(float(np.std(values)), 6),
                "median": round(float(np.median(values)), 6),
                "min": round(float(np.min(values)), 6),
                "max": round(float(np.max(values)), 6),
                "p10": round(float(np.percentile(values, 10)), 6),
                "p25": round(float(np.percentile(values, 25)), 6),
                "p75": round(float(np.percentile(values, 75)), 6),
                "p90": round(float(np.percentile(values, 90)), 6),
            }

        baseline = BaselineStatistics(
            water_body_id=water_body_id,
            num_observations=num_obs,
            status="valid",
            date_range=date_range,
            water_area_stats=_compute_stats(areas),
            turbidity_stats=_compute_stats(turbs),
            chlorophyll_stats=_compute_stats(chlors),
            algal_stats=_compute_stats(algals),
        )

        logger.info(
            f"Baseline computed for '{water_body_id}': {num_obs} observations, "
            f"status=valid, area_mean={baseline.water_area_stats['mean']:.3f} km2"
        )
        return baseline

    def get_observation_count(self, water_body_id: str) -> int:
        """Return the number of historical observations for a water body."""
        if water_body_id not in self._histories:
            self.load_history(water_body_id)
        return len(self._histories.get(water_body_id, []))

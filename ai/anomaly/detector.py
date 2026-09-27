"""
Anomaly Detection Module.
Simple, explainable detector comparing current observation indicators
against historical baseline statistics.

Output schema:
{
    "anomaly_score": float,       # [0.0, 1.0]
    "anomaly_level": str,         # "NONE" | "LOW" | "MEDIUM" | "HIGH"
    "affected_area_km2": float,
    "explanation": [str, ...]     # Fixed taxonomy entries only
}

DESIGN PRINCIPLES:
- Explanations map to a FIXED TAXONOMY tied to actually computed z-scores
  and threshold deviations. Never freeform or invented text.
- If baseline is 'insufficient', anomaly detection is skipped with a
  clear 'insufficient_baseline' status.
- All thresholds are documented and deterministic.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

import numpy as np

from ai.features.baseline import BaselineStatistics

logger = logging.getLogger("AquaSentinel.AnomalyDetector")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [AnomalyDetector] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ── FIXED EXPLANATION TAXONOMY ──────────────────────────────────────────
# Every explanation string is constructed from this taxonomy.
# No freeform text is ever generated.

class AnomalyTaxonomy:
    """Fixed taxonomy of anomaly explanation templates."""

    # Turbidity anomalies
    TURBIDITY_ELEVATED = "TURBIDITY_ELEVATED: Turbidity indicator ({value:.4f}) is {z_score:.1f} standard deviations above baseline mean ({baseline_mean:.4f}), suggesting increased suspended sediment or particulate matter."
    TURBIDITY_DEPRESSED = "TURBIDITY_DEPRESSED: Turbidity indicator ({value:.4f}) is {z_score:.1f} standard deviations below baseline mean ({baseline_mean:.4f}), suggesting unusually clear water conditions."

    # Chlorophyll anomalies
    CHLOROPHYLL_ELEVATED = "CHLOROPHYLL_ELEVATED: Chlorophyll indicator ({value:.4f}) is {z_score:.1f} standard deviations above baseline mean ({baseline_mean:.4f}), suggesting increased phytoplankton activity or nutrient loading."
    CHLOROPHYLL_DEPRESSED = "CHLOROPHYLL_DEPRESSED: Chlorophyll indicator ({value:.4f}) is {z_score:.1f} standard deviations below baseline mean ({baseline_mean:.4f}), suggesting reduced biological productivity."

    # Algal anomalies
    ALGAL_ELEVATED = "ALGAL_ELEVATED: Algal indicator ({value:.4f}) is {z_score:.1f} standard deviations above baseline mean ({baseline_mean:.4f}), suggesting potential algal bloom or floating vegetation."
    ALGAL_DEPRESSED = "ALGAL_DEPRESSED: Algal indicator ({value:.4f}) is {z_score:.1f} standard deviations below baseline mean ({baseline_mean:.4f}), suggesting reduced surface algal presence."

    # Water area anomalies
    AREA_INCREASE = "AREA_INCREASE: Water surface area ({value:.3f} km2) is {z_score:.1f} standard deviations above baseline mean ({baseline_mean:.3f} km2), suggesting water level rise or flooding."
    AREA_DECREASE = "AREA_DECREASE: Water surface area ({value:.3f} km2) is {z_score:.1f} standard deviations below baseline mean ({baseline_mean:.3f} km2), suggesting water level decline or drought conditions."

    # Combined / compound anomalies
    COMPOUND_TURBIDITY_CHLOROPHYLL = "COMPOUND_ANOMALY: Both turbidity and chlorophyll indicators are simultaneously elevated, suggesting possible runoff event carrying nutrients and sediment."
    COMPOUND_CHLOROPHYLL_ALGAL = "COMPOUND_ANOMALY: Both chlorophyll and algal indicators are simultaneously elevated, suggesting active algal bloom conditions."


# Anomaly level thresholds (based on composite anomaly score)
ANOMALY_THRESHOLDS = {
    "NONE": (0.0, 0.25),
    "LOW": (0.25, 0.50),
    "MEDIUM": (0.50, 0.75),
    "HIGH": (0.75, 1.0),
}

# Z-score threshold for individual indicator anomalies
Z_SCORE_THRESHOLD = 1.5


@dataclass
class AnomalyResult:
    """Anomaly detection output for a single observation."""
    water_body_id: str
    observation_date: str
    anomaly_score: float          # [0.0, 1.0]
    anomaly_level: str            # "NONE", "LOW", "MEDIUM", "HIGH"
    affected_area_km2: float
    explanation: List[str]        # Fixed taxonomy entries
    baseline_status: str          # "valid", "insufficient", "insufficient_baseline"
    individual_scores: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AnomalyDetector:
    """
    Explainable anomaly detector comparing current observation
    against historical baseline statistics.
    """

    def __init__(
        self,
        z_score_threshold: float = Z_SCORE_THRESHOLD,
        turbidity_weight: float = 0.30,
        chlorophyll_weight: float = 0.30,
        algal_weight: float = 0.25,
        area_weight: float = 0.15,
    ):
        self.z_threshold = z_score_threshold
        self.weights = {
            "turbidity": turbidity_weight,
            "chlorophyll": chlorophyll_weight,
            "algal": algal_weight,
            "area": area_weight,
        }

    def detect(
        self,
        water_body_id: str,
        observation_date: str,
        current_turbidity: float,
        current_chlorophyll: float,
        current_algal: float,
        current_water_area_km2: float,
        baseline: BaselineStatistics,
    ) -> AnomalyResult:
        """
        Compare current observation against baseline and produce anomaly assessment.

        If baseline.status != 'valid', returns a no-detection result with
        baseline_status='insufficient_baseline'.
        """
        if baseline.status != "valid":
            logger.info(
                f"Baseline for '{water_body_id}' is '{baseline.status}'. "
                "Skipping anomaly detection."
            )
            return AnomalyResult(
                water_body_id=water_body_id,
                observation_date=observation_date,
                anomaly_score=0.0,
                anomaly_level="NONE",
                affected_area_km2=0.0,
                explanation=[],
                baseline_status="insufficient_baseline",
            )

        explanations: List[str] = []
        individual_scores: Dict[str, float] = {}

        # Compute per-indicator z-scores and anomaly contributions
        turb_score, turb_explanations = self._score_indicator(
            value=current_turbidity,
            stats=baseline.turbidity_stats,
            elevated_template=AnomalyTaxonomy.TURBIDITY_ELEVATED,
            depressed_template=AnomalyTaxonomy.TURBIDITY_DEPRESSED,
        )
        individual_scores["turbidity"] = turb_score
        explanations.extend(turb_explanations)

        chl_score, chl_explanations = self._score_indicator(
            value=current_chlorophyll,
            stats=baseline.chlorophyll_stats,
            elevated_template=AnomalyTaxonomy.CHLOROPHYLL_ELEVATED,
            depressed_template=AnomalyTaxonomy.CHLOROPHYLL_DEPRESSED,
        )
        individual_scores["chlorophyll"] = chl_score
        explanations.extend(chl_explanations)

        alg_score, alg_explanations = self._score_indicator(
            value=current_algal,
            stats=baseline.algal_stats,
            elevated_template=AnomalyTaxonomy.ALGAL_ELEVATED,
            depressed_template=AnomalyTaxonomy.ALGAL_DEPRESSED,
        )
        individual_scores["algal"] = alg_score
        explanations.extend(alg_explanations)

        area_score, area_explanations = self._score_indicator(
            value=current_water_area_km2,
            stats=baseline.water_area_stats,
            elevated_template=AnomalyTaxonomy.AREA_INCREASE,
            depressed_template=AnomalyTaxonomy.AREA_DECREASE,
        )
        individual_scores["area"] = area_score
        explanations.extend(area_explanations)

        # Compound explanations describe simultaneous elevation, so a
        # large absolute anomaly score is not sufficient by itself.
        turbidity_elevated = current_turbidity > baseline.turbidity_stats.get("mean", 0.0)
        chlorophyll_elevated = current_chlorophyll > baseline.chlorophyll_stats.get("mean", 0.0)
        algal_elevated = current_algal > baseline.algal_stats.get("mean", 0.0)

        if (
            turb_score > 0.5
            and chl_score > 0.5
            and turbidity_elevated
            and chlorophyll_elevated
        ):
            explanations.append(AnomalyTaxonomy.COMPOUND_TURBIDITY_CHLOROPHYLL)

        if (
            chl_score > 0.5
            and alg_score > 0.5
            and chlorophyll_elevated
            and algal_elevated
        ):
            explanations.append(AnomalyTaxonomy.COMPOUND_CHLOROPHYLL_ALGAL)

        # Weighted composite anomaly score
        composite = (
            self.weights["turbidity"] * turb_score
            + self.weights["chlorophyll"] * chl_score
            + self.weights["algal"] * alg_score
            + self.weights["area"] * area_score
        )
        anomaly_score = round(min(1.0, max(0.0, composite)), 4)

        # Determine level
        anomaly_level = self._score_to_level(anomaly_score)

        # Affected area: proportional to anomaly score * water area
        affected_area_km2 = round(anomaly_score * current_water_area_km2, 4)

        logger.info(
            f"Anomaly detection for '{water_body_id}': "
            f"score={anomaly_score:.4f}, level={anomaly_level}, "
            f"affected_area={affected_area_km2:.3f} km2, "
            f"explanations={len(explanations)}"
        )

        return AnomalyResult(
            water_body_id=water_body_id,
            observation_date=observation_date,
            anomaly_score=anomaly_score,
            anomaly_level=anomaly_level,
            affected_area_km2=affected_area_km2,
            explanation=explanations,
            baseline_status="valid",
            individual_scores=individual_scores,
        )

    def _score_indicator(
        self,
        value: float,
        stats: Dict[str, float],
        elevated_template: str,
        depressed_template: str,
    ) -> tuple:
        """
        Compute anomaly score for a single indicator based on z-score deviation.
        Returns (score_0_to_1, list_of_explanation_strings).
        """
        mean = stats.get("mean", 0.0)
        std = stats.get("std", 0.0)

        # Avoid division by zero for constant baselines
        if std < 1e-8:
            # If std is essentially zero, any deviation is anomalous
            if abs(value - mean) < 1e-6:
                return 0.0, []
            z_score = 3.0  # Flag as significant
        else:
            z_score = abs(value - mean) / std

        # Normalize z-score to [0, 1] using sigmoid-like mapping
        # z=0 -> 0, z=1.5 -> ~0.5, z=3 -> ~0.9
        score = 1.0 - 1.0 / (1.0 + (z_score / self.z_threshold) ** 2)
        score = round(min(1.0, max(0.0, score)), 4)

        explanations = []
        if z_score >= self.z_threshold:
            if value > mean:
                explanation = elevated_template.format(
                    value=value, z_score=z_score, baseline_mean=mean
                )
            else:
                explanation = depressed_template.format(
                    value=value, z_score=z_score, baseline_mean=mean
                )
            explanations.append(explanation)

        return score, explanations

    def _score_to_level(self, score: float) -> str:
        """Map anomaly score to discrete level."""
        for level, (low, high) in ANOMALY_THRESHOLDS.items():
            if low <= score < high:
                return level
        return "HIGH"  # score == 1.0

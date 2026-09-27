import tempfile
import unittest
from pathlib import Path

from ai.features.baseline import HistoricalBaseline, ObservationRecord


class HistoricalBaselineQualityTests(unittest.TestCase):
    def _record(self, date: str, status: str, value: float) -> ObservationRecord:
        return ObservationRecord(
            water_body_id="WB_TEST",
            observation_date=date,
            source_reference=f"S2_{date}",
            water_area_km2=value,
            turbidity_indicator=value,
            chlorophyll_indicator=value,
            algal_indicator=value,
            cloud_percentage=0.0,
            mask_quality_status=status,
            mode="prototype_indicator_only",
        )

    def test_low_quality_observations_do_not_enter_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = HistoricalBaseline(Path(tmp))
            manager.add_observation(
                self._record("2024-01-01T00:00:00Z", "ok", 0.10)
            )
            manager.add_observation(
                self._record("2024-02-01T00:00:00Z", "low_confidence_mask", 0.90)
            )
            manager.add_observation(
                self._record("2024-03-01T00:00:00Z", "ok", 0.20)
            )

            baseline = manager.compute_baseline("WB_TEST")

            self.assertEqual(baseline.status, "insufficient")
            self.assertEqual(baseline.num_observations, 2)

    def test_warning_observations_remain_baseline_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = HistoricalBaseline(Path(tmp))
            manager.add_observation(
                self._record("2024-01-01T00:00:00Z", "ok", 0.10)
            )
            manager.add_observation(
                self._record("2024-02-01T00:00:00Z", "ok_with_warning", 0.20)
            )
            manager.add_observation(
                self._record("2024-03-01T00:00:00Z", "ok", 0.30)
            )

            baseline = manager.compute_baseline("WB_TEST")

            self.assertEqual(baseline.status, "valid")
            self.assertEqual(baseline.num_observations, 3)
            self.assertAlmostEqual(baseline.turbidity_stats["mean"], 0.20)

    def test_three_quality_passed_observations_make_valid_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = HistoricalBaseline(Path(tmp))
            for idx, value in enumerate((0.10, 0.20, 0.30), start=1):
                manager.add_observation(
                    self._record(
                        f"2024-0{idx}-01T00:00:00Z",
                        "ok",
                        value,
                    )
                )

            baseline = manager.compute_baseline("WB_TEST")

            self.assertEqual(baseline.status, "valid")
            self.assertEqual(baseline.num_observations, 3)
            self.assertAlmostEqual(baseline.turbidity_stats["mean"], 0.20)


if __name__ == "__main__":
    unittest.main()

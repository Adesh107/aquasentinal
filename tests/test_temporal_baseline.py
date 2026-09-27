import unittest

from app.services.ai_pipeline import _prior_baseline
from ai.features.baseline import ObservationRecord


class _FakeBaselineManager:
    def __init__(self, history):
        self._stored = list(history)
        self._histories = {}

    def load_history(self, water_body_id):
        self._histories[water_body_id] = list(self._stored)
        return self._histories[water_body_id]

    def compute_baseline(self, water_body_id):
        history = self._histories[water_body_id]
        return {
            "count": len(history),
            "dates": [record.observation_date for record in history],
        }


def _record(date: str) -> ObservationRecord:
    return ObservationRecord(
        water_body_id="WB_TEST",
        observation_date=date,
        source_reference=f"S2_{date}",
        water_area_km2=0.1,
        turbidity_indicator=0.2,
        chlorophyll_indicator=0.3,
        algal_indicator=0.4,
        cloud_percentage=0.0,
        mask_quality_status="ok",
        mode="prototype_indicator_only",
    )


class TemporalBaselineTests(unittest.TestCase):
    def test_only_strictly_prior_observations_are_used(self):
        manager = _FakeBaselineManager(
            [
                _record("2024-01-19T05:31:49.024000+00:00"),
                _record("2024-05-03T05:26:51.024000+00:00"),
                _record("2024-05-18T05:26:49.024000+00:00"),
                _record("2024-06-01T05:26:49.024000+00:00"),
            ]
        )

        baseline = _prior_baseline(
            manager,
            "WB_TEST",
            "2024-05-18T05:26:49.024000+00:00",
        )

        self.assertEqual(baseline["count"], 2)
        self.assertEqual(
            baseline["dates"],
            [
                "2024-01-19T05:31:49.024000+00:00",
                "2024-05-03T05:26:51.024000+00:00",
            ],
        )

    def test_history_is_restored_after_baseline_computation(self):
        records = [
            _record("2024-01-19T05:31:49.024000+00:00"),
            _record("2024-05-18T05:26:49.024000+00:00"),
            _record("2024-06-01T05:26:49.024000+00:00"),
        ]
        manager = _FakeBaselineManager(records)

        _prior_baseline(
            manager,
            "WB_TEST",
            "2024-05-18T05:26:49.024000+00:00",
        )

        self.assertEqual(manager._histories["WB_TEST"], records)


if __name__ == "__main__":
    unittest.main()

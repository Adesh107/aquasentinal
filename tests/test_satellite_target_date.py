import unittest
from datetime import datetime, timezone

from ai.satellite.client import PlanetaryComputerSentinelClient


class _FakeAsset:
    def __init__(self, href="https://example.test/asset"):
        self.href = href


class _FakeItem:
    def __init__(self, item_id, obs_date, cloud):
        self.id = item_id
        self.datetime = datetime.fromisoformat(obs_date).replace(tzinfo=timezone.utc)
        self.properties = {
            "eo:cloud_cover": cloud,
            "platform": "sentinel-2",
        }
        self.assets = {}
        self.bbox = [73.8, 18.5, 73.9, 18.6]
        self.geometry = {
            "type": "Polygon",
            "coordinates": [],
        }


class _FakeSearch:
    def __init__(self, items):
        self._items = items

    def items(self):
        return iter(self._items)


class _FakeCatalog:
    def __init__(self, items):
        self._items = items
        self.last_search_kwargs = None

    def search(self, **kwargs):
        self.last_search_kwargs = kwargs
        return _FakeSearch(self._items)


class TargetDateSelectionTests(unittest.TestCase):
    def test_closest_acquisition_wins_over_lower_cloud_farther_away(self):
        client = PlanetaryComputerSentinelClient.__new__(PlanetaryComputerSentinelClient)
        client._catalog = _FakeCatalog(
            [
                _FakeItem(
                    "older-clear-scene",
                    "2024-05-03T05:26:51",
                    0.01,
                ),
                _FakeItem(
                    "target-nearby-scene",
                    "2024-05-18T05:26:49",
                    1.47,
                ),
            ]
        )

        result = client.search_observation(
            water_body_id="WB_TEST",
            bbox=[73.8, 18.5, 73.9, 18.6],
            target_date="2024-05-18T05:26:49+00:00",
            initial_window_days=15,
            initial_cloud_threshold=20.0,
        )

        self.assertEqual(result.source_reference, "target-nearby-scene")


if __name__ == "__main__":
    unittest.main()

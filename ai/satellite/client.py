"""
Microsoft Planetary Computer Sentinel-2 L2A STAC Client.
Handles satellite scene discovery, metadata preservation, and resilient query window
widening guards for Maharashtra water bodies.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field, asdict

import pystac_client
import planetary_computer

logger = logging.getLogger("AquaSentinel.SatelliteClient")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [SatelliteClient] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

PLANETARY_COMPUTER_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION_SENTINEL_2 = "sentinel-2-l2a"


@dataclass
class ObservationQualityInfo:
    """Metadata preserving satellite acquisition quality and atmospheric attributes."""
    cloud_cover_percentage: float
    nodata_pixel_percentage: Optional[float] = None
    high_proba_clouds_percentage: Optional[float] = None
    water_percentage: Optional[float] = None
    vegetation_percentage: Optional[float] = None
    sun_elevation: Optional[float] = None
    sun_azimuth: Optional[float] = None
    processing_baseline: Optional[str] = None
    scl_available: bool = False
    raw_properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SentinelObservation:
    """
    Preserves all mandated parameters for a Sentinel-2 L2A acquisition.
    Never discards water_body_id, observation_date, satellite_name, cloud_percentage,
    source/reference, or quality_info.
    """
    water_body_id: str
    observation_date: str
    satellite_name: str
    cloud_percentage: float
    source_reference: str  # STAC Item ID
    quality_info: ObservationQualityInfo
    assets: Dict[str, str]  # Band key to signed URL
    bbox: List[float]
    geometry: Dict[str, Any]
    window_widened: bool = False
    widening_attempts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize observation to structured dictionary."""
        data = asdict(self)
        return data


class PlanetaryComputerSentinelClient:
    """STAC Client interfacing with Microsoft Planetary Computer."""

    def __init__(self, stac_api_url: str = PLANETARY_COMPUTER_STAC_URL):
        self.stac_api_url = stac_api_url
        logger.info(f"Initializing Planetary Computer STAC client with endpoint: {stac_api_url}")
        self._catalog = pystac_client.Client.open(
            stac_api_url,
            modifier=planetary_computer.sign_inplace
        )

    def get_stac_catalog(self) -> pystac_client.Client:
        return self._catalog

    def search_observation(
        self,
        water_body_id: str,
        bbox: List[float],
        target_date: str,
        initial_window_days: int = 15,
        initial_cloud_threshold: float = 20.0,
        max_window_days: int = 90,
        max_cloud_threshold: float = 60.0,
        step_days: int = 15,
        step_cloud: float = 10.0,
    ) -> SentinelObservation:
        """
        Search for a Sentinel-2 L2A observation matching the geometry and target date.
        
        GUARD: If zero cloud-free observations exist in the initial window,
        automatically widens the temporal window and cloud threshold step-by-step
        and logs each attempt. Does not fail silently and does not fail loudly
        without retry.
        """
        # Parse target date
        if "T" in target_date:
            center_dt = datetime.fromisoformat(target_date.replace("Z", "+00:00"))
        else:
            center_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        current_window_days = initial_window_days
        current_cloud_threshold = initial_cloud_threshold
        widening_logs: List[str] = []
        is_widened = False

        while True:
            start_dt = center_dt - timedelta(days=current_window_days)
            end_dt = center_dt + timedelta(days=current_window_days)
            date_range_str = f"{start_dt.strftime('%Y-%m-%d')}/{end_dt.strftime('%Y-%m-%d')}"

            attempt_msg = (
                f"Querying S2-L2A for '{water_body_id}' | Window: {date_range_str} "
                f"(±{current_window_days}d) | Cloud cover < {current_cloud_threshold}%"
            )
            logger.info(attempt_msg)
            widening_logs.append(attempt_msg)

            search = self._catalog.search(
                collections=[COLLECTION_SENTINEL_2],
                bbox=bbox,
                datetime=date_range_str,
                query={"eo:cloud_cover": {"lt": current_cloud_threshold}},
                sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}]
            )

            items = list(search.items())
            if items:
                # Select the acquisition closest to the requested observation date.
                # Cloud cover remains the tie-breaker so the query does not
                # silently substitute a much older/later scene just because it
                # has lower cloud cover.
                def _selection_key(item):
                    item_dt = item.datetime
                    if item_dt is None:
                        return (float("inf"), float(item.properties.get("eo:cloud_cover", 100.0)))
                    if item_dt.tzinfo is None:
                        item_dt = item_dt.replace(tzinfo=timezone.utc)
                    item_dt = item_dt.astimezone(timezone.utc)
                    center_utc = center_dt.astimezone(timezone.utc)
                    return (
                        abs((item_dt - center_utc).total_seconds()),
                        float(item.properties.get("eo:cloud_cover", 100.0)),
                    )

                best_item = min(items, key=_selection_key)
                matched_msg = (
                    f"Found {len(items)} matching observations. Selected closest scene: "
                    f"ID={best_item.id}, CloudCover={best_item.properties.get('eo:cloud_cover', 'N/A')}%, "
                    f"ObsDate={best_item.datetime.isoformat()}"
                )
                logger.info(matched_msg)
                widening_logs.append(matched_msg)
                return self._parse_stac_item(
                    item=best_item,
                    water_body_id=water_body_id,
                    is_widened=is_widened,
                    widening_logs=widening_logs
                )

            # GUARD TRIGGERED: No observation found in current window
            is_widened = True
            guard_msg = (
                f"[GUARD TRIGGERED] Zero observations with cloud < {current_cloud_threshold}% "
                f"within ±{current_window_days} days of {center_dt.strftime('%Y-%m-%d')}."
            )
            logger.warning(guard_msg)
            widening_logs.append(guard_msg)

            can_widen_window = (current_window_days + step_days) <= max_window_days
            can_widen_cloud = (current_cloud_threshold + step_cloud) <= max_cloud_threshold

            if not can_widen_window and not can_widen_cloud:
                err_msg = (
                    f"Guard exceeded maximum widening limits (±{max_window_days} days, "
                    f"<{max_cloud_threshold}% cloud). Zero Sentinel-2 observations found for "
                    f"water_body_id '{water_body_id}' around {target_date}."
                )
                logger.error(err_msg)
                widening_logs.append(err_msg)
                raise FileNotFoundError(err_msg)

            if can_widen_window:
                current_window_days += step_days
            if can_widen_cloud:
                current_cloud_threshold += step_cloud

            logger.info(
                f"[GUARD RETRY] Widening search criteria -> ±{current_window_days} days, "
                f"cloud threshold < {current_cloud_threshold}%"
            )

    def get_observation_by_id(
        self,
        item_id: str,
        water_body_id: str,
    ) -> SentinelObservation:
        """Directly retrieve a specific Sentinel-2 L2A STAC item by ID."""
        logger.info(f"Directly fetching STAC item '{item_id}' for water body '{water_body_id}'")
        collection = self._catalog.get_collection(COLLECTION_SENTINEL_2)
        item = collection.get_item(item_id) if collection else None
        if item is None:
            raise FileNotFoundError(f"STAC Item '{item_id}' not found in '{COLLECTION_SENTINEL_2}'")
        return self._parse_stac_item(
            item=item,
            water_body_id=water_body_id,
            is_widened=False,
            widening_logs=[f"Direct retrieval by item ID: {item_id}"],
        )

    def _parse_stac_item(
        self,
        item: Any,
        water_body_id: str,
        is_widened: bool,
        widening_logs: List[str]
    ) -> SentinelObservation:
        """Extract and preserve all required metadata from a STAC item."""
        props = item.properties
        cloud_pct = float(props.get("eo:cloud_cover", 0.0))
        satellite_name = str(props.get("platform", "Sentinel-2"))
        if "s2:granule_id" in props:
            # Often contains S2A or S2B
            granule = props["s2:granule_id"]
            if granule.startswith("S2A"):
                satellite_name = "Sentinel-2A"
            elif granule.startswith("S2B"):
                satellite_name = "Sentinel-2B"

        obs_date = item.datetime.isoformat() if item.datetime else str(props.get("datetime", ""))
        source_ref = str(item.id)

        quality_info = ObservationQualityInfo(
            cloud_cover_percentage=cloud_pct,
            nodata_pixel_percentage=props.get("s2:nodata_pixel_percentage"),
            high_proba_clouds_percentage=props.get("s2:high_proba_clouds_percentage"),
            water_percentage=props.get("s2:water_percentage"),
            vegetation_percentage=props.get("s2:vegetation_percentage"),
            sun_elevation=props.get("view:sun_elevation"),
            sun_azimuth=props.get("view:sun_azimuth"),
            processing_baseline=props.get("s2:processing_baseline"),
            scl_available=("SCL" in item.assets),
            raw_properties={
                "id": item.id,
                "platform": props.get("platform"),
                "instruments": props.get("instruments"),
                "constellation": props.get("constellation"),
                "grid:code": props.get("grid:code"),
                "s2:mgrs_tile": props.get("s2:mgrs_tile"),
            }
        )

        # Retain band assets URLs
        assets_dict: Dict[str, str] = {}
        for band_key, asset in item.assets.items():
            assets_dict[band_key] = asset.href

        return SentinelObservation(
            water_body_id=water_body_id,
            observation_date=obs_date,
            satellite_name=satellite_name,
            cloud_percentage=cloud_pct,
            source_reference=source_ref,
            quality_info=quality_info,
            assets=assets_dict,
            bbox=list(item.bbox),
            geometry=item.geometry,
            window_widened=is_widened,
            widening_attempts=widening_logs
        )

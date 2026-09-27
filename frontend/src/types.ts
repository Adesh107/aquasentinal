export type PolygonGeometry = {
  type: "Polygon";
  coordinates: number[][][];
};

export type WaterBody = {
  id: number;
  name: string;
  type: string | null;
  district: string | null;
  state: string;
  geometry: PolygonGeometry;
  area_sq_km: number | null;
  source: string;
  active: boolean;
};

export type SatelliteObservation = {
  id: number;
  water_body_id: number;
  satellite: string;
  observation_date: string;
  scene_id: string;
  cloud_percentage: number | null;
  quality_score: number | null;
  source_url: string | null;
  observation_metadata: Record<string, unknown> | null;
  created_at: string;
};

export type AnalysisData = {
  turbidity: number | null;
  chlorophyll: number | null;
  anomaly_score: number | null;
  anomaly_detected: boolean;
  confidence: number | null;
  evidence: string[];
  affected_area_km2?: number | null;
  geojson?: AnalysisGeoJson;
  spatial_anomaly?: AnomalySpatialData;
};

export type AnalysisResult = {
  id: number;
  observation_id: number;
  model_name: string;
  model_version: string | null;
  analysis_data: AnalysisData;
  created_at: string;
};

export type Alert = {
  id: number;
  water_body_id: number;
  analysis_id: number | null;
  date: string;
  indicator: string;
  severity: string;
  confidence: number | null;
  affected_area_km2: number | null;
  explanation: Record<string, unknown> | unknown[] | null;
  status: string;
  created_at: string;
};

export type GeoJsonGeometry =
  | PolygonGeometry
  | {
      type: "MultiPolygon";
      coordinates: number[][][][];
    };

export type GeoJsonFeature = {
  type: "Feature";
  id?: number | string;
  properties: Record<string, unknown>;
  geometry: GeoJsonGeometry;
};

export type GeoJsonFeatureCollection = {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
};

export type AnomalySpatialData = {
  mode: string;
  anomalous_pixels: number;
  confidence: number | null;
};

export type AnalysisGeoJson = {
  water_boundary?: GeoJsonFeature | null;
  anomaly_regions?: GeoJsonFeatureCollection | null;
};

export type TimelineEntry = {
  observation_id: number;
  observation_date: string;
  satellite: string;
  scene_id: string;
  cloud_percentage: number | null;
  quality_score: number | null;
  analysis_id: number | null;
  model_name: string | null;
  model_version: string | null;
  turbidity: number | null;
  chlorophyll: number | null;
  anomaly_score: number | null;
  anomaly_detected: boolean;
  confidence: number | null;
  evidence: string[];
};

export type TrendPoint = {
  observation_id: number;
  observation_date: string;
  turbidity: number | null;
  chlorophyll: number | null;
  anomaly_score: number | null;
  anomaly_detected: boolean;
  confidence: number | null;
};

export type TrendResponse = {
  water_body_id: number;
  from_date: string | null;
  to_date: string | null;
  observation_count: number;
  analyzed_observation_count: number;
  anomaly_count: number;
  summary: {
    turbidity_min: number | null;
    turbidity_max: number | null;
    chlorophyll_min: number | null;
    chlorophyll_max: number | null;
    anomaly_score_min: number | null;
    anomaly_score_max: number | null;
  };
  series: TrendPoint[];
};

export type ComparisonSnapshot = {
  observation_id: number;
  observation_date: string;
  analysis_id: number;
  model_name: string;
  model_version: string | null;
  turbidity: number | null;
  chlorophyll: number | null;
  anomaly_score: number | null;
  anomaly_detected: boolean;
  confidence: number | null;
  evidence: string[];
};

export type ComparisonResponse = {
  water_body_id: number;
  from_date: string | null;
  to_date: string | null;
  comparison_available: boolean;
  reason?: string;
  earlier: ComparisonSnapshot | null;
  latest: ComparisonSnapshot | null;
  change: {
    turbidity: number | null;
    chlorophyll: number | null;
    anomaly_score: number | null;
    confidence: number | null;
  };
};

export type AnomalyHistoryResponse = {
  water_body_id: number;
  from_date: string | null;
  to_date: string | null;
  anomaly_count: number;
  anomalies: ComparisonSnapshot[];
};
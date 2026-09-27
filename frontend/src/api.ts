import type {
  Alert,
  AnalysisResult,
  AnomalyHistoryResponse,
  ComparisonResponse,
  GeoJsonFeature,
  GeoJsonFeatureCollection,
  SatelliteObservation,
  TrendResponse,
  WaterBody,
} from "./types";

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the HTTP status message.
    }
    throw new ApiError(response.status, message);
  }

  return (await response.json()) as T;
}

function query(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export async function getWaterBodies(filters?: {
  district?: string;
  type?: string;
}) {
  return request<WaterBody[]>(
    `/water-bodies${query(filters || {})}`,
  );
}

export async function discoverWaterBodies(limit = 60) {
  return request<{
    source: string;
    endpoint: string;
    requested_limit: number;
    discovered: number;
    imported: number;
    updated: number;
    water_bodies: Array<{
      id: number;
      name: string;
      type: string | null;
      district: string | null;
      area_sq_km: number | null;
      source: string;
      osm_id: number | null;
    }>;
  }>(`/water-bodies/discover${query({ limit })}`, {
    method: "POST",
  });
}

export async function getWaterBodiesEnsuringDiscovery() {
  const current = await getWaterBodies();
  const hasRealImportedWaterBodies = current.some(
    (waterBody) => waterBody.source.toLowerCase() === "openstreetmap",
  );

  // Keep existing manual records, but make sure a fresh database/demo instance
  // also gets a real Maharashtra water-body inventory.
  if (hasRealImportedWaterBodies) return current;

  await discoverWaterBodies(60);
  return getWaterBodies();
}

export async function getNearbyWaterBodies(
  latitude: number,
  longitude: number,
  radiusKm = 5,
) {
  return request<(WaterBody & { distance_km: number })[]>(
    `/water-bodies/nearby${query({
      latitude,
      longitude,
      radius_km: radiusKm,
    })}`,
  );
}

export async function getWaterBody(id: number) {
  return request<WaterBody>(`/water-bodies/${id}`);
}

export async function getWaterBodyGeometry(id: number) {
  return request<GeoJsonFeature>(`/water-bodies/${id}/geometry`);
}

export async function createWaterBody(payload: {
  name: string;
  type?: string | null;
  district?: string | null;
  state?: string;
  geometry: WaterBody["geometry"];
}) {
  return request<WaterBody>("/water-bodies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateWaterBody(
  id: number,
  payload: Partial<{
    name: string;
    type: string | null;
    district: string | null;
    state: string;
    geometry: WaterBody["geometry"];
    active: boolean;
  }>,
) {
  return request<WaterBody>(`/water-bodies/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteWaterBody(id: number) {
  return request<{ message: string; id: number }>(`/water-bodies/${id}`, {
    method: "DELETE",
  });
}

export async function getSatelliteObservations(waterBodyId?: number) {
  return request<SatelliteObservation[]>(
    `/satellite-observations${query({ water_body_id: waterBodyId })}`,
  );
}

export async function getSatelliteObservation(id: number) {
  return request<SatelliteObservation>(`/satellite-observations/${id}`);
}

export async function createSatelliteObservation(payload: Omit<SatelliteObservation, "id" | "created_at">) {
  return request<SatelliteObservation>("/satellite-observations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getAnalysisResults(observationId?: number) {
  return request<AnalysisResult[]>(
    `/analysis-results${query({ observation_id: observationId })}`,
  );
}

export async function getAnalysisResultsForWaterBody(id: number) {
  return request<AnalysisResult[]>(
    `/analysis-results/water-bodies/${id}/analysis-results`,
  );
}

export async function getLatestAnalysisForObservation(id: number) {
  return request<AnalysisResult>(
    `/analysis-results/satellite-observations/${id}/latest-analysis`,
  );
}

export async function getAnalysisResult(id: number) {
  return request<AnalysisResult>(`/analysis-results/${id}`);
}

export async function createAnalysisResult(payload: {
  observation_id: number;
  model_name: string;
  model_version?: string | null;
  analysis_data: AnalysisResult["analysis_data"];
}) {
  return request<AnalysisResult>("/analysis-results", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getAlerts(filters?: {
  water_body_id?: number;
  from_date?: string;
  to_date?: string;
}) {
  return request<Alert[]>(
    `/alerts${query(filters || {})}`,
  );
}

export async function getAlert(id: number) {
  return request<Alert>(`/alerts/${id}`);
}

export async function getActiveAlertGeometries() {
  return request<GeoJsonFeatureCollection>("/alerts/geometries");
}

export async function getAlertGeometry(id: number) {
  return request<GeoJsonFeature | GeoJsonFeatureCollection>(`/alerts/${id}/geometry`);
}

export async function createAlert(payload: {
  water_body_id: number;
  analysis_id?: number | null;
  date: string;
  indicator: string;
  severity: string;
  confidence?: number | null;
  affected_area_km2?: number | null;
  explanation?: Record<string, unknown> | unknown[] | null;
  geometry?: WaterBody["geometry"] | null;
  status?: string;
}) {
  return request<Alert>("/alerts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getTimeline(
  id: number,
  fromDate?: string,
  toDate?: string,
) {
  return request<unknown[]>(
    `/water-bodies/${id}/timeline${query({
      from_date: fromDate,
      to_date: toDate,
    })}`,
  );
}

export async function getTrend(
  id: number,
  fromDate?: string,
  toDate?: string,
) {
  return request<TrendResponse>(
    `/water-bodies/${id}/trend${query({
      from_date: fromDate,
      to_date: toDate,
    })}`,
  );
}

export async function getComparison(
  id: number,
  fromDate?: string,
  toDate?: string,
) {
  return request<ComparisonResponse>(
    `/water-bodies/${id}/comparison${query({
      from_date: fromDate,
      to_date: toDate,
    })}`,
  );
}

export async function getAnomalyHistory(
  id: number,
  fromDate?: string,
  toDate?: string,
) {
  return request<AnomalyHistoryResponse>(
    `/water-bodies/${id}/anomaly-history${query({
      from_date: fromDate,
      to_date: toDate,
    })}`,
  );
}

export async function getBackendStatus() {
  return request<{ message: string; status: string }>("/");
}
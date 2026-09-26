import {
  AlertTriangle,
  BarChart3,
  Bell,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Cloud,
  Database,
  Droplets,
  ExternalLink,
  Filter,
  Gauge,
  History,
  Layers3,
  MapPin,
  Menu,
  RefreshCw,
  Satellite,
  Search,
  ShieldCheck,
  Sparkles,
  Waves,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type DependencyList, type ReactNode } from "react";
import {
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  BrowserRouter,
  NavLink,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import * as maplibregl from "maplibre-gl";

import {
  API_BASE_URL,
  ApiError,
  getAlertGeometry,
  getAlerts,
  getAnalysisResults,
  getAnalysisResultsForWaterBody,
  getAnomalyHistory,
  getBackendStatus,
  getComparison,
  getSatelliteObservations,
  getTimeline,
  getTrend,
  getWaterBodies,
  getWaterBody,
  getWaterBodyGeometry,
  getNearbyWaterBodies,
} from "./api";
import type {
  Alert,
  AnalysisResult,
  AnomalyHistoryResponse,
  ComparisonResponse,
  GeoJsonFeature,
  SatelliteObservation,
  TrendResponse,
  WaterBody,
} from "./types";

type AsyncState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
};

function useAsync<T>(
  loader: () => Promise<T>,
  deps: DependencyList,
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    setState({ data: null, loading: true, error: null });
    loader()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          data: null,
          loading: false,
          error: error instanceof Error ? error.message : "Request failed",
        });
      });
    return () => {
      cancelled = true;
    };
  }, deps);

  return state;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDateShort(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
  }).format(date);
}

function numberOrDash(value: number | null | undefined, digits = 2) {
  return value == null || Number.isNaN(value) ? "—" : value.toFixed(digits);
}

function percentOrDash(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? "—" : `${(value * 100).toFixed(0)}%`;
}

function deltaLabel(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function severityClass(severity: string) {
  const normalized = severity.toLowerCase();
  if (normalized.includes("critical") || normalized.includes("high")) return "severity high";
  if (normalized.includes("medium") || normalized.includes("moderate")) return "severity medium";
  return "severity low";
}

function anomalyClass(anomaly: boolean | null | undefined) {
  return anomaly ? "status-badge alert" : "status-badge success";
}

function EmptyState({
  title,
  text,
  icon = <Database size={20} />,
}: {
  title: string;
  text: string;
  icon?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <div className="empty-title">{title}</div>
      <div className="empty-text">{text}</div>
    </div>
  );
}

function ErrorState({
  title = "Could not load this view",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-state">
      <div className="empty-icon error-icon"><CircleAlert size={20} /></div>
      <div className="empty-title">{title}</div>
      <div className="empty-text">{message}</div>
      {onRetry && <button className="button outline small" onClick={onRetry}><RefreshCw size={14} /> Retry</button>}
    </div>
  );
}

function LoadingRows({ count = 5 }: { count?: number }) {
  return (
    <div className="loading-list">
      {Array.from({ length: count }).map((_, index) => (
        <div className="skeleton-row" key={index}>
          <div className="skeleton skeleton-wide" />
          <div className="skeleton skeleton-mid" />
          <div className="skeleton skeleton-small" />
        </div>
      ))}
    </div>
  );
}

function BackendStatus() {
  const [state, setState] = useState<"checking" | "up" | "down">("checking");
  const check = () => {
    setState("checking");
    getBackendStatus()
      .then(() => setState("up"))
      .catch(() => setState("down"));
  };
  useEffect(check, []);
  return (
    <button className="connection-pill" onClick={check} title={`API: ${API_BASE_URL}`}>
      <span className={`connection-dot ${state}`} />
      <span>{state === "checking" ? "Checking API" : state === "up" ? "API connected" : "API offline"}</span>
    </button>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const items = [
    { to: "/", label: "Overview", icon: Gauge, end: true },
    { to: "/water-bodies", label: "Water Bodies", icon: Droplets },
    { to: "/alerts", label: "Alerts", icon: Bell },
    { to: "/history", label: "History", icon: History },
    { to: "/observations", label: "Observations", icon: Satellite },
  ];
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><Waves size={18} /></div>
        <div>
          <div className="brand-name">AquaSentinel</div>
          <div className="brand-meta">Water intelligence</div>
        </div>
      </div>
      <div className="sidebar-status">
        <div className="status-icon"><ShieldCheck size={16} /></div>
        <div>
          <div className="status-title">Decision support</div>
          <div className="status-subtitle">Satellite monitoring console</div>
        </div>
      </div>
      <nav className="nav-list" aria-label="Primary">
        {items.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
          >
            <Icon size={17} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="scientific-note">
          <AlertTriangle size={15} />
          <span>Satellite outputs are early monitoring and should not replace lab testing.</span>
        </div>
        <div className="version-note">AquaSentinel • backend API v0.2</div>
      </div>
    </aside>
  );
}

function Shell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <button className={`mobile-backdrop ${mobileOpen ? "show" : ""}`} onClick={() => setMobileOpen(false)} aria-label="Close navigation" />
      <div className={`mobile-sidebar ${mobileOpen ? "show" : ""}`}>
        <Sidebar onNavigate={() => setMobileOpen(false)} />
      </div>
      <div className="desktop-sidebar"><Sidebar /></div>
      <div className="main-column">
        <header className="topbar">
          <div className="mobile-heading">
            <button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={19} /></button>
            <button className="mobile-brand" onClick={() => navigate("/")}><Waves size={17} /> AquaSentinel</button>
          </div>
          <div className="topbar-right">
            <BackendStatus />
            <div className="api-target" title={API_BASE_URL}>{API_BASE_URL}</div>
          </div>
        </header>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/water-bodies" element={<WaterBodiesPage />} />
            <Route path="/water-bodies/:id" element={<WaterBodyDetailPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/observations" element={<ObservationsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

function PageHeader({
  eyebrow,
  title,
  text,
  actions,
}: {
  eyebrow: string;
  title: string;
  text?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        {text && <p>{text}</p>}
      </div>
      {actions && <div className="header-actions">{actions}</div>}
    </div>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  note,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="summary-card">
      <div className="summary-icon">{icon}</div>
      <div className="summary-label">{label}</div>
      <div className="summary-value">{value}</div>
      <div className="summary-note">{note}</div>
    </div>
  );
}

type MapFeature = WaterBody & { hasActiveAlert: boolean };

function WaterBodyMap({
  waterBodies,
  alerts = [],
  selectedId,
  onSelect,
  alertFeature,
  height = 450,
}: {
  waterBodies: WaterBody[];
  alerts?: Alert[];
  selectedId?: number | null;
  onSelect?: (id: number) => void;
  alertFeature?: GeoJsonFeature | null;
  height?: number;
}) {
  const nodeRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const features = useMemo<MapFeature[]>(() => {
    const activeAlerts = new Set(
      alerts.filter((a) => a.status.toLowerCase() === "active").map((a) => a.water_body_id),
    );
    return waterBodies.map((waterBody) => ({
      ...waterBody,
      hasActiveAlert: activeAlerts.has(waterBody.id),
    }));
  }, [waterBodies, alerts]);

  const featureCollection = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: features.map((waterBody) => ({
        type: "Feature" as const,
        id: waterBody.id,
        properties: {
          id: waterBody.id,
          name: waterBody.name,
          district: waterBody.district ?? "",
          hasActiveAlert: waterBody.hasActiveAlert,
        },
        geometry: waterBody.geometry,
      })),
    }),
    [features],
  );

  const alertCollection = useMemo(
    () =>
      alertFeature
        ? {
            type: "FeatureCollection" as const,
            features: [alertFeature],
          }
        : { type: "FeatureCollection" as const, features: [] },
    [alertFeature],
  );

  useEffect(() => {
    if (!nodeRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: nodeRef.current,
      center: [75.2, 19.2],
      zoom: 5.3,
      minZoom: 4,
      maxZoom: 16,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-right");
    map.on("load", () => {
      map.addSource("water-bodies", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "water-body-fill",
        type: "fill",
        source: "water-bodies",
        paint: {
          "fill-color": ["case", ["get", "hasActiveAlert"], "#b84a3c", "#1e8074"],
          "fill-opacity": 0.18,
        },
      });
      map.addLayer({
        id: "water-body-line",
        type: "line",
        source: "water-bodies",
        paint: {
          "line-color": ["case", ["get", "hasActiveAlert"], "#b84a3c", "#0f6b61"],
          "line-width": 1.5,
        },
      });
      map.addLayer({
        id: "water-body-points",
        type: "circle",
        source: "water-bodies",
        paint: {
          "circle-radius": ["case", ["==", ["get", "id"], selectedId ?? -1], 8, 5],
          "circle-color": ["case", ["get", "hasActiveAlert"], "#b84a3c", "#0f6b61"],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });
      map.addSource("alert-geometry", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "alert-fill",
        type: "fill",
        source: "alert-geometry",
        paint: {
          "fill-color": "#b84a3c",
          "fill-opacity": 0.26,
        },
      });
      map.addLayer({
        id: "alert-line",
        type: "line",
        source: "alert-geometry",
        paint: {
          "line-color": "#b84a3c",
          "line-width": 3,
        },
      });

      const clickHandler = (event: maplibregl.MapLayerMouseEvent) => {
        const id = Number(event.features?.[0]?.properties?.id);
        if (Number.isFinite(id)) onSelectRef.current?.(id);
      };
      map.on("click", "water-body-points", clickHandler);
      map.on("click", "water-body-fill", clickHandler);
      map.on("mouseenter", "water-body-points", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "water-body-points", () => { map.getCanvas().style.cursor = ""; });
      map.on("mouseenter", "water-body-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "water-body-fill", () => { map.getCanvas().style.cursor = ""; });
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource("water-bodies") as maplibregl.GeoJSONSource | undefined;
    source?.setData(featureCollection);
    const selectedLayer = map.getLayer("water-body-points");
    if (selectedLayer) {
      map.setPaintProperty("water-body-points", "circle-radius", ["case", ["==", ["get", "id"], selectedId ?? -1], 8, 5]);
    }
    const alertSource = map.getSource("alert-geometry") as maplibregl.GeoJSONSource | undefined;
    alertSource?.setData(alertCollection);

    if (features.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      features.forEach((waterBody) => {
        waterBody.geometry.coordinates[0]?.forEach(([lng, lat]) => bounds.extend([lng, lat]));
      });
      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 50, maxZoom: 9, duration: 400 });
      }
    }
  }, [featureCollection, alertCollection, selectedId, features]);

  return <div className="map-container" style={{ height }}><div ref={nodeRef} className="map-canvas" />{waterBodies.length === 0 && <div className="map-empty"><MapPin size={18} /><span>No water-body geometry returned by the API.</span></div>}</div>;
}

function OverviewPage() {
  const navigate = useNavigate();
  const waterBodies = useAsync(getWaterBodies, []);
  const alerts = useAsync(() => getAlerts(), []);
  const observations = useAsync(() => getSatelliteObservations(), []);
  const analyses = useAsync(() => getAnalysisResults(), []);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const selected = waterBodies.data?.find((item) => item.id === selectedId) ?? waterBodies.data?.[0] ?? null;
  const activeAlerts = alerts.data?.filter((a) => a.status.toLowerCase() === "active") ?? [];
  const recentAlerts = [...(alerts.data ?? [])].sort((a, b) => +new Date(b.date) - +new Date(a.date)).slice(0, 5);
  const anyError = waterBodies.error || alerts.error || observations.error || analyses.error;

  return (
    <div>
      <PageHeader
        eyebrow="MAHARASHTRA • MONITORING CONSOLE"
        title="Water quality intelligence"
        text="Map-first review of satellite observations, analysis evidence, trends, and alerts."
        actions={
          <>
            <button className="button outline" onClick={() => navigate("/water-bodies")}><Droplets size={15} /> Water bodies</button>
            <button className="button primary" onClick={() => navigate("/alerts")}><Bell size={15} /> Review alerts</button>
          </>
        }
      />

      {anyError && (
        <div className="inline-warning">
          <CircleAlert size={15} />
          <span>Some panels could not load. Check the API connection and retry the affected view.</span>
        </div>
      )}

      <div className="summary-grid">
        <SummaryCard icon={<Droplets size={16} />} label="Water bodies" value={waterBodies.data ? String(waterBodies.data.length) : "—"} note="Active records returned by API" />
        <SummaryCard icon={<Satellite size={16} />} label="Observations" value={observations.data ? String(observations.data.length) : "—"} note="Satellite observations stored" />
        <SummaryCard icon={<AlertTriangle size={16} />} label="Open alerts" value={alerts.data ? String(activeAlerts.length) : "—"} note="Alerts with active status" />
        <SummaryCard icon={<BarChart3 size={16} />} label="Analyzed observations" value={analyses.data ? String(analyses.data.length) : "—"} note="Analysis results returned" />
      </div>

      <section className="panel map-panel">
        <div className="panel-header">
          <div>
            <div className="panel-kicker">GEOSPATIAL OVERVIEW</div>
            <div className="panel-title">Maharashtra water-body watchlist</div>
          </div>
          <div className="legend">
            <span><i className="legend-dot monitored" /> Monitored</span>
            <span><i className="legend-dot alert" /> Active alert</span>
          </div>
        </div>
        {waterBodies.loading ? <div className="map-loading"><div className="skeleton skeleton-full" /></div> :
          waterBodies.error ? <ErrorState message={waterBodies.error} /> :
          <WaterBodyMap waterBodies={waterBodies.data ?? []} alerts={alerts.data ?? []} selectedId={selected?.id} onSelect={setSelectedId} />}
        <div className="map-panel-footer">
          <div>
            <span className="footer-label">Selected</span>
            <strong>{selected?.name ?? "No water body selected"}</strong>
            {selected?.district && <span>• {selected.district}</span>}
          </div>
          {selected && <button className="button ghost small" onClick={() => navigate(`/water-bodies/${selected.id}`)}>Open detail <ChevronRight size={14} /></button>}
        </div>
      </section>

      <section className="overview-grid">
        <div className="panel">
          <div className="panel-header">
            <div>
              <div className="panel-kicker">RECENT ALERTS</div>
              <div className="panel-title">Review queue</div>
            </div>
            <button className="button ghost small" onClick={() => navigate("/alerts")}>View all <ChevronRight size={14} /></button>
          </div>
          {alerts.loading ? <LoadingRows count={3} /> :
            alerts.data?.length === 0 ? <EmptyState title="No alerts returned" text="The alert service has not returned any records." icon={<Bell size={20} />} /> :
            <div className="alert-list">
              {recentAlerts.map((alert) => (
                <button className="alert-row" key={alert.id} onClick={() => navigate(`/alerts?alert=${alert.id}`)}>
                  <div className="alert-icon"><AlertTriangle size={15} /></div>
                  <div className="alert-main">
                    <div className="alert-topline"><span>{alert.indicator}</span><span className={severityClass(alert.severity)}>{alert.severity}</span></div>
                    <div className="alert-title">{alert.explanation && !Array.isArray(alert.explanation) && typeof alert.explanation === "object" && "title" in alert.explanation ? String(alert.explanation.title) : `Alert #${alert.id}`}</div>
                    <div className="alert-text">{formatDate(alert.date)} • {percentOrDash(alert.confidence)} confidence • {alert.status}</div>
                  </div>
                  <ChevronRight size={15} className="muted" />
                </button>
              ))}
            </div>}
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <div className="panel-kicker">DATA QUALITY</div>
              <div className="panel-title">Observation coverage</div>
            </div>
            <button className="button ghost small" onClick={() => navigate("/observations")}>Inspect <ChevronRight size={14} /></button>
          </div>
          {observations.loading ? <LoadingRows count={4} /> :
            observations.data?.length === 0 ? <EmptyState title="No observations available" text="Observation rows will appear here once satellite scenes are ingested." icon={<Satellite size={20} />} /> :
            <div className="quality-list">
              {observations.data.slice(0, 6).map((observation) => (
                <div className="quality-row" key={observation.id}>
                  <div className="quality-symbol"><Cloud size={15} /></div>
                  <div>
                    <strong>{observation.scene_id}</strong>
                    <span>{observation.satellite} • {formatDateShort(observation.observation_date)}</span>
                  </div>
                  <div className="quality-values">
                    <span>Cloud <strong>{observation.cloud_percentage == null ? "—" : `${observation.cloud_percentage.toFixed(1)}%`}</strong></span>
                    <span>Score <strong>{numberOrDash(observation.quality_score, 2)}</strong></span>
                  </div>
                </div>
              ))}
            </div>}
        </div>
      </section>
    </div>
  );
}

function WaterBodiesPage() {
  const navigate = useNavigate();
  const state = useAsync(() => getWaterBodies(), []);
  const [search, setSearch] = useState("");
  const [district, setDistrict] = useState("");
  const [type, setType] = useState("");
  const [nearby, setNearby] = useState<(WaterBody & { distance_km: number })[] | null>(null);
  const [nearbyError, setNearbyError] = useState<string | null>(null);

  const districts = useMemo(() => [...new Set((state.data ?? []).map((x) => x.district).filter(Boolean))].sort() as string[], [state.data]);
  const types = useMemo(() => [...new Set((state.data ?? []).map((x) => x.type).filter(Boolean))].sort() as string[], [state.data]);

  const filtered = useMemo(() => (state.data ?? []).filter((waterBody) => {
    const searchOk = !search || [waterBody.name, waterBody.district, waterBody.type].filter(Boolean).some((value) => String(value).toLowerCase().includes(search.toLowerCase()));
    const districtOk = !district || waterBody.district === district;
    const typeOk = !type || waterBody.type === type;
    return searchOk && districtOk && typeOk;
  }), [state.data, search, district, type]);

  async function findNearby() {
    setNearbyError(null);
    if (!navigator.geolocation) {
      setNearbyError("Geolocation is not available in this browser.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          setNearby(await getNearbyWaterBodies(position.coords.latitude, position.coords.longitude, 25));
        } catch (error) {
          setNearbyError(error instanceof Error ? error.message : "Nearby search failed");
        }
      },
      (error) => setNearbyError(error.message || "Location permission was denied."),
      { enableHighAccuracy: false, timeout: 10000 },
    );
  }

  return (
    <div>
      <PageHeader eyebrow="WATER BODY REGISTRY" title="Water bodies" text="Filter active water bodies, inspect footprints, and open detailed monitoring views." actions={<button className="button outline" onClick={findNearby}><MapPin size={15} /> Find nearby</button>} />
      {nearbyError && <div className="inline-warning"><MapPin size={15} /> {nearbyError}</div>}
      {nearby && <div className="nearby-panel"><div><strong>Nearby water bodies</strong><span>Within 25 km of your browser location</span></div><button className="button ghost small" onClick={() => setNearby(null)}>Hide</button><div className="nearby-list">{nearby.map((item) => <button className="nearby-chip" key={item.id} onClick={() => navigate(`/water-bodies/${item.id}`)}><span>{item.name}</span><b>{item.distance_km.toFixed(1)} km</b></button>)}</div></div>}
      <div className="filter-bar">
        <label className="search-field"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search water body, district or type" /></label>
        <label className="field"><span>District</span><select value={district} onChange={(event) => setDistrict(event.target.value)}><option value="">All districts</option>{districts.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="field"><span>Type</span><select value={type} onChange={(event) => setType(event.target.value)}><option value="">All types</option>{types.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <div className="filter-summary"><Filter size={14} /> {filtered.length} shown</div>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div><div className="panel-kicker">ACTIVE RECORDS</div><div className="panel-title">Water-body inventory</div></div>
          <div className="table-note">Source: FastAPI /water-bodies</div>
        </div>
        {state.loading ? <LoadingRows count={7} /> : state.error ? <ErrorState message={state.error} /> : filtered.length === 0 ? <EmptyState title="No water bodies match" text="Try a different district, type, or search term." icon={<Droplets size={20} />} /> :
          <div className="table-scroll"><table><thead><tr><th>Name</th><th>District</th><th>Type</th><th>Area</th><th>Source</th><th></th></tr></thead><tbody>
            {filtered.map((waterBody) => <tr key={waterBody.id}><td><button className="table-link" onClick={() => navigate(`/water-bodies/${waterBody.id}`)}>{waterBody.name}</button></td><td>{waterBody.district ?? "—"}</td><td>{waterBody.type ?? "—"}</td><td>{waterBody.area_sq_km == null ? "—" : `${waterBody.area_sq_km.toFixed(2)} km²`}</td><td><span className="source-tag">{waterBody.source}</span></td><td><button className="icon-button" onClick={() => navigate(`/water-bodies/${waterBody.id}`)} aria-label={`Open ${waterBody.name}`}><ChevronRight size={16} /></button></td></tr>)}
          </tbody></table></div>}
      </section>
    </div>
  );
}

function WaterBodyDetailPage() {
  const navigate = useNavigate();
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const waterBody = useAsync(() => getWaterBody(id), [id]);
  const geometry = useAsync(() => getWaterBodyGeometry(id), [id]);
  const observations = useAsync(() => getSatelliteObservations(id), [id]);
  const analyses = useAsync(() => getAnalysisResultsForWaterBody(id), [id]);
  const trend = useAsync(() => getTrend(id), [id]);
  const comparison = useAsync(() => getComparison(id), [id]);
  const anomalies = useAsync(() => getAnomalyHistory(id), [id]);
  const alerts = useAsync(() => getAlerts({ water_body_id: id }), [id]);

  const latestObservation = observations.data?.[0] ?? null;
  const latestAnalysis = analyses.data?.[0] ?? null;
  const activeAlert = alerts.data?.find((a) => a.status.toLowerCase() === "active") ?? null;
  const [metric, setMetric] = useState<"turbidity" | "chlorophyll" | "anomaly_score">("anomaly_score");

  if (!Number.isFinite(id)) return <Navigate to="/water-bodies" replace />;
  if (waterBody.error) return <ErrorState message={waterBody.error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      <div className="breadcrumb"><button onClick={() => navigate("/water-bodies")}><ChevronLeft size={14} /> Water bodies</button><ChevronRight size={13} /><span>{waterBody.data?.name ?? "Water body"}</span></div>
      <PageHeader
        eyebrow="WATER BODY DETAIL"
        title={waterBody.data?.name ?? "Loading…"}
        text={waterBody.data ? [waterBody.data.district, waterBody.data.type, waterBody.data.state].filter(Boolean).join(" • ") : undefined}
        actions={<>{activeAlert && <span className="status-badge alert"><AlertTriangle size={13} /> Active alert</span>}<button className="button outline" onClick={() => navigate(`/history?waterBody=${id}`)}><History size={14} /> Historical view</button></>}
      />

      {activeAlert && <div className="alert-banner"><AlertTriangle size={16} /><div><strong>{activeAlert.indicator} • {activeAlert.severity}</strong><span>Alert #{activeAlert.id} • {formatDate(activeAlert.date)} • {percentOrDash(activeAlert.confidence)} confidence</span></div><button className="button ghost small" onClick={() => navigate(`/alerts?alert=${activeAlert.id}`)}>Inspect <ChevronRight size={14} /></button></div>}

      {waterBody.loading ? <div className="loading-card"><div className="skeleton skeleton-title" /><div className="skeleton skeleton-wide" /></div> :
        waterBody.data && <div className="detail-grid-top">
          <div className="panel footprint-panel">
            <div className="panel-header"><div><div className="panel-kicker">DIGITAL FOOTPRINT</div><div className="panel-title">Water-body layout</div></div>{waterBody.data.area_sq_km != null && <span className="area-pill">{waterBody.data.area_sq_km.toFixed(2)} km²</span>}</div>
            <WaterBodyMap waterBodies={[waterBody.data]} alerts={alerts.data ?? []} selectedId={id} height={360} />
          </div>
          <div className="panel">
            <div className="panel-header"><div><div className="panel-kicker">SATELLITE OBSERVATION</div><div className="panel-title">Latest scene</div></div><Satellite size={17} className="muted" /></div>
            {observations.loading ? <LoadingRows count={5} /> : !latestObservation ? <EmptyState title="No observation available" text="The backend has no satellite observation for this water body yet." icon={<Satellite size={20} />} /> :
              <div className="detail-list">
                <div className="detail-row"><span>Satellite</span><strong>{latestObservation.satellite}</strong></div>
                <div className="detail-row"><span>Observation date</span><strong>{formatDate(latestObservation.observation_date)}</strong></div>
                <div className="detail-row"><span>Scene ID</span><strong className="mono">{latestObservation.scene_id}</strong></div>
                <div className="detail-row"><span>Cloud percentage</span><strong>{latestObservation.cloud_percentage == null ? "—" : `${latestObservation.cloud_percentage.toFixed(1)}%`}</strong></div>
                <div className="detail-row"><span>Quality score</span><strong>{numberOrDash(latestObservation.quality_score, 2)}</strong></div>
                {latestObservation.source_url && <a className="detail-link" href={latestObservation.source_url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open source scene</a>}
                {latestObservation.observation_metadata && <details className="metadata-box"><summary>Observation metadata</summary><pre>{JSON.stringify(latestObservation.observation_metadata, null, 2)}</pre></details>}
              </div>}
          </div>
        </div>}

      <section className="panel">
        <div className="panel-header"><div><div className="panel-kicker">LATEST ANALYSIS</div><div className="panel-title">Indicator snapshot</div></div>{latestAnalysis && <span className="model-tag">{latestAnalysis.model_name}{latestAnalysis.model_version ? ` • ${latestAnalysis.model_version}` : ""}</span>}</div>
        {analyses.loading ? <LoadingRows count={2} /> : !latestAnalysis ? <EmptyState title="No analysis result" text="The observation exists, but there is no stored analysis result to display." icon={<BarChart3 size={20} />} /> :
          <div className="metric-grid">
            <MetricCard label="Turbidity" value={numberOrDash(latestAnalysis.analysis_data.turbidity)} note="Reported by analysis" />
            <MetricCard label="Chlorophyll indicator" value={numberOrDash(latestAnalysis.analysis_data.chlorophyll)} note="Reported by analysis" />
            <MetricCard label="Anomaly score" value={numberOrDash(latestAnalysis.analysis_data.anomaly_score)} note={latestAnalysis.analysis_data.anomaly_detected ? "Anomaly detected" : "No anomaly detected"} status={latestAnalysis.analysis_data.anomaly_detected ? "alert" : "success"} />
            <MetricCard label="Confidence" value={percentOrDash(latestAnalysis.analysis_data.confidence)} note="Analysis confidence" />
          </div>}
        {latestAnalysis?.analysis_data.evidence?.length ? <div className="evidence-strip"><div className="evidence-heading"><Sparkles size={14} /> Supporting evidence</div><div className="evidence-list">{latestAnalysis.analysis_data.evidence.map((item, index) => <span key={index}>{item}</span>)}</div></div> : null}
      </section>

      <section className="detail-grid">
        <div className="panel">
          <div className="panel-header">
            <div><div className="panel-kicker">TEMPORAL ANALYSIS</div><div className="panel-title">Historical trend</div></div>
            <div className="segmented">{([["anomaly_score", "Anomaly"], ["turbidity", "Turbidity"], ["chlorophyll", "Chlorophyll"]] as const).map(([key, label]) => <button key={key} className={metric === key ? "active" : ""} onClick={() => setMetric(key)}>{label}</button>)}</div>
          </div>
          {trend.loading ? <div className="chart-loading"><div className="skeleton skeleton-full" /></div> :
            trend.error ? <ErrorState message={trend.error} /> :
            !trend.data?.series?.length ? <EmptyState title="No timeline data" text="The trend endpoint returned no observations for this water body." icon={<BarChart3 size={20} />} /> :
            <TrendChart response={trend.data} metric={metric} />}
        </div>

        <div className="panel">
          <div className="panel-header"><div><div className="panel-kicker">BEFORE / AFTER</div><div className="panel-title">Comparison</div></div><Layers3 size={17} className="muted" /></div>
          {comparison.loading ? <LoadingRows count={4} /> : comparison.error ? <ErrorState message={comparison.error} /> :
            comparison.data && <ComparisonView response={comparison.data} />}
        </div>
      </section>

      <section className="detail-grid">
        <div className="panel">
          <div className="panel-header"><div><div className="panel-kicker">ANOMALY HISTORY</div><div className="panel-title">Flagged observations</div></div><span className="count-pill">{anomalies.data?.anomaly_count ?? 0}</span></div>
          {anomalies.loading ? <LoadingRows count={3} /> : anomalies.error ? <ErrorState message={anomalies.error} /> :
            anomalies.data?.anomalies.length ? <div className="anomaly-history">{anomalies.data.anomalies.map((item) => <div className="anomaly-card" key={item.analysis_id}><div className="anomaly-date">{formatDate(item.observation_date)}</div><div className="anomaly-head"><span className="status-badge alert"><AlertTriangle size={13} /> Detected</span><strong>Score {numberOrDash(item.anomaly_score)}</strong><span>{percentOrDash(item.confidence)} confidence</span></div><div className="anomaly-evidence">{item.evidence.map((evidence, index) => <span key={index}>{evidence}</span>)}</div></div>)}</div> :
            <EmptyState title="No anomalies in history" text="No anomaly_detected=true records were returned for the selected water body." icon={<CheckCircle2 size={20} />} />}
        </div>

        <div className="panel">
          <div className="panel-header"><div><div className="panel-kicker">OBSERVATION HISTORY</div><div className="panel-title">Latest scenes</div></div><button className="button ghost small" onClick={() => navigate(`/observations?waterBody=${id}`)}>View all <ChevronRight size={14} /></button></div>
          {observations.loading ? <LoadingRows count={4} /> : observations.data?.length ? <div className="compact-table"><table><thead><tr><th>Date</th><th>Scene</th><th>Cloud</th><th>Quality</th></tr></thead><tbody>{observations.data.slice(0, 6).map((item) => <tr key={item.id}><td>{formatDateShort(item.observation_date)}</td><td className="mono">{item.scene_id}</td><td>{item.cloud_percentage == null ? "—" : `${item.cloud_percentage.toFixed(1)}%`}</td><td>{numberOrDash(item.quality_score)}</td></tr>)}</tbody></table></div> : <EmptyState title="No observations" text="No satellite scenes are stored for this water body." icon={<Satellite size={20} />} />}
        </div>
      </section>
    </div>
  );
}

function MetricCard({ label, value, note, status }: { label: string; value: string; note: string; status?: "success" | "alert" }) {
  return <div className={`metric-card ${status ?? ""}`}><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-note">{note}</div></div>;
}

function TrendChart({ response, metric }: { response: TrendResponse; metric: "turbidity" | "chlorophyll" | "anomaly_score" }) {
  const label = metric === "anomaly_score" ? "Anomaly score" : metric === "chlorophyll" ? "Chlorophyll indicator" : "Turbidity";
  const color = metric === "anomaly_score" ? "#b84a3c" : "#0f6b61";
  const data = response.series.map((point) => ({ ...point, dateLabel: formatDateShort(point.observation_date), value: point[metric] }));
  return <div className="chart-wrap"><div className="chart-summary"><span>{label}</span><strong>{response.observation_count} observations • {response.analyzed_observation_count} analyzed • {response.anomaly_count} anomalies</strong></div><ResponsiveContainer width="100%" height={280}><LineChart data={data} margin={{ top: 12, right: 14, left: -10, bottom: 0 }}><CartesianGrid stroke="#dbe6e2" strokeDasharray="3 3" /><XAxis dataKey="dateLabel" tick={{ fill: "#60736f", fontSize: 11 }} tickLine={false} axisLine={false} /><YAxis tick={{ fill: "#60736f", fontSize: 11 }} tickLine={false} axisLine={false} domain={["auto", "auto"]} /><Tooltip formatter={(value) => [value == null ? "—" : Number(value).toFixed(3), label]} labelFormatter={(labelValue) => `Observation ${labelValue}`} /><Line type="monotone" dataKey="value" stroke={color} strokeWidth={2.5} dot={{ r: 3, strokeWidth: 1, stroke: "#ffffff" }} connectNulls /></LineChart></ResponsiveContainer></div>;
}

function ComparisonView({ response }: { response: ComparisonResponse }) {
  if (!response.comparison_available || !response.earlier || !response.latest) return <EmptyState title="Comparison not available" text={response.reason ?? "At least two analyzed observations are required."} icon={<Layers3 size={20} />} />;
  const rows = [
    ["Turbidity", response.earlier.turbidity, response.latest.turbidity, response.change.turbidity],
    ["Chlorophyll", response.earlier.chlorophyll, response.latest.chlorophyll, response.change.chlorophyll],
    ["Anomaly score", response.earlier.anomaly_score, response.latest.anomaly_score, response.change.anomaly_score],
    ["Confidence", response.earlier.confidence, response.latest.confidence, response.change.confidence],
  ] as const;
  return <div className="comparison"><div className="compare-dates"><span><small>Earlier</small><strong>{formatDate(response.earlier.observation_date)}</strong></span><ChevronRight size={15} /><span><small>Latest</small><strong>{formatDate(response.latest.observation_date)}</strong></span></div><div className="compare-table">{rows.map(([label, earlier, latest, change]) => <div className="compare-row" key={label}><span>{label}</span><strong>{label === "Confidence" ? percentOrDash(earlier) : numberOrDash(earlier)}</strong><strong>{label === "Confidence" ? percentOrDash(latest) : numberOrDash(latest)}</strong><b className={change != null && change < 0 ? "delta negative" : "delta"}>{change == null ? "—" : label === "Confidence" ? percentOrDash(change) : deltaLabel(change)}</b></div>)}</div><div className="compare-legend"><span /> Earlier <span className="latest-dot" /> Latest <span className="delta-chip">Δ</span> Change</div></div>;
}

function AlertsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedAlertId = Number(searchParams.get("alert")) || null;
  const [waterBodyFilter, setWaterBodyFilter] = useState<number | "">("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const alerts = useAsync(() => getAlerts({
    water_body_id: waterBodyFilter === "" ? undefined : waterBodyFilter,
    from_date: fromDate ? `${fromDate}T00:00:00` : undefined,
    to_date: toDate ? `${toDate}T23:59:59` : undefined,
  }), [waterBodyFilter, fromDate, toDate]);
  const waterBodies = useAsync(() => getWaterBodies(), []);
  const selectedAlert = alerts.data?.find((alert) => alert.id === selectedAlertId) ?? null;
  const alertGeometry = useAsync(() => selectedAlert ? getAlertGeometry(selectedAlert.id) : Promise.resolve(null), [selectedAlert?.id]);

  return (
    <div>
      <PageHeader eyebrow="ALERT CENTER" title="Alerts" text="Review machine-generated flags with severity, confidence, affected area, geometry, and explanation evidence." />
      <div className="filter-bar">
        <label className="field"><span>Water body</span><select value={waterBodyFilter} onChange={(e) => setWaterBodyFilter(e.target.value ? Number(e.target.value) : "")}><option value="">All water bodies</option>{(waterBodies.data ?? []).map((wb) => <option value={wb.id} key={wb.id}>{wb.name}</option>)}</select></label>
        <label className="field"><span>From</span><input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} /></label>
        <label className="field"><span>To</span><input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} /></label>
        <button className="button ghost small" onClick={() => { setWaterBodyFilter(""); setFromDate(""); setToDate(""); }}><X size={14} /> Clear</button>
        <div className="filter-summary"><Bell size={14} /> {alerts.data?.length ?? "—"} alerts</div>
      </div>

      <div className="alert-layout">
        <section className="panel">
          <div className="panel-header"><div><div className="panel-kicker">ALERT QUEUE</div><div className="panel-title">Detected events</div></div><div className="table-note">GET /alerts</div></div>
          {alerts.loading ? <LoadingRows count={7} /> : alerts.error ? <ErrorState message={alerts.error} /> : alerts.data?.length === 0 ? <EmptyState title="No alerts returned" text="The selected filters did not return any alert records." icon={<Bell size={20} />} /> :
            <div className="table-scroll"><table><thead><tr><th>Date</th><th>Water body</th><th>Indicator</th><th>Severity</th><th>Confidence</th><th>Area</th><th></th></tr></thead><tbody>
              {alerts.data.map((alert) => <tr className={selectedAlertId === alert.id ? "selected-row" : ""} key={alert.id}><td>{formatDateShort(alert.date)}</td><td>{waterBodies.data?.find((wb) => wb.id === alert.water_body_id)?.name ?? `#${alert.water_body_id}`}</td><td>{alert.indicator}</td><td><span className={severityClass(alert.severity)}>{alert.severity}</span></td><td>{percentOrDash(alert.confidence)}</td><td>{alert.affected_area_km2 == null ? "—" : `${alert.affected_area_km2.toFixed(2)} km²`}</td><td><button className="icon-button" onClick={() => setSearchParams({ alert: String(alert.id) })}><ChevronRight size={15} /></button></td></tr>)}
            </tbody></table></div>}
        </section>

        <aside className="panel alert-detail">
          {!selectedAlert ? <EmptyState title="Select an alert" text="Choose an alert row to inspect its geometry, explanation, and supporting analysis reference." icon={<AlertTriangle size={20} />} /> :
            <>
              <div className="panel-header"><div><div className="panel-kicker">ALERT DETAIL • #{selectedAlert.id}</div><div className="panel-title">{selectedAlert.indicator} • {selectedAlert.severity}</div></div><button className="icon-button" onClick={() => setSearchParams({})} aria-label="Close alert detail"><X size={15} /></button></div>
              <div className="detail-list">
                <div className="detail-row"><span>Water body</span><strong>{waterBodies.data?.find((wb) => wb.id === selectedAlert.water_body_id)?.name ?? `#${selectedAlert.water_body_id}`}</strong></div>
                <div className="detail-row"><span>Date</span><strong>{formatDate(selectedAlert.date)}</strong></div>
                <div className="detail-row"><span>Confidence</span><strong>{percentOrDash(selectedAlert.confidence)}</strong></div>
                <div className="detail-row"><span>Affected area</span><strong>{selectedAlert.affected_area_km2 == null ? "—" : `${selectedAlert.affected_area_km2.toFixed(2)} km²`}</strong></div>
                <div className="detail-row"><span>Status</span><strong>{selectedAlert.status}</strong></div>
                <div className="detail-row"><span>Analysis reference</span><strong>{selectedAlert.analysis_id == null ? "—" : `#${selectedAlert.analysis_id}`}</strong></div>
              </div>
              <div className="explanation-box"><div className="evidence-heading"><Sparkles size={14} /> Explanation</div>{selectedAlert.explanation ? <pre>{JSON.stringify(selectedAlert.explanation, null, 2)}</pre> : <span>No explanation payload returned for this alert.</span>}</div>
              <div className="alert-geometry"><div className="map-caption"><span>Alert footprint</span><span>{alertGeometry.loading ? "Loading geometry…" : alertGeometry.data ? "Geometry available" : "No geometry"}</span></div><WaterBodyMap waterBodies={[]} alertFeature={alertGeometry.data ?? null} height={270} /></div>
              {alertGeometry.error && <div className="inline-warning"><CircleAlert size={14} /> {alertGeometry.error}</div>}
            </>}
        </aside>
      </div>
    </div>
  );
}

function HistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = Number(searchParams.get("waterBody")) || 0;
  const waterBodies = useAsync(() => getWaterBodies(), []);
  const id = selectedId || waterBodies.data?.[0]?.id || 0;
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const commonFrom = fromDate ? `${fromDate}T00:00:00` : undefined;
  const commonTo = toDate ? `${toDate}T23:59:59` : undefined;
  const trend = useAsync(() => id ? getTrend(id, commonFrom, commonTo) : Promise.resolve(null), [id, commonFrom, commonTo]);
  const comparison = useAsync(() => id ? getComparison(id, commonFrom, commonTo) : Promise.resolve(null), [id, commonFrom, commonTo]);
  const anomalies = useAsync(() => id ? getAnomalyHistory(id, commonFrom, commonTo) : Promise.resolve(null), [id, commonFrom, commonTo]);
  const timeline = useAsync(() => id ? getTimeline(id, commonFrom, commonTo) : Promise.resolve([]), [id, commonFrom, commonTo]);

  const selected = waterBodies.data?.find((wb) => wb.id === id);
  const [metric, setMetric] = useState<"turbidity" | "chlorophyll" | "anomaly_score">("anomaly_score");

  return (
    <div>
      <PageHeader eyebrow="HISTORICAL ANALYSIS" title="History" text="Timeline, trends, before/after comparison and anomaly history for a selected water body." />
      <div className="filter-bar">
        <label className="field wide"><span>Water body</span><select value={id || ""} onChange={(e) => setSearchParams(e.target.value ? { waterBody: e.target.value } : {})}><option value="">Select water body</option>{(waterBodies.data ?? []).map((wb) => <option key={wb.id} value={wb.id}>{wb.name}</option>)}</select></label>
        <label className="field"><span>From</span><input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} /></label>
        <label className="field"><span>To</span><input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} /></label>
      </div>

      {selected && <div className="context-strip"><div><div className="panel-kicker">SELECTED WATER BODY</div><strong>{selected.name}</strong><span>{selected.district ?? "Maharashtra"} • {selected.type ?? "Water body"}</span></div><div className="context-metrics"><span>Observations <b>{trend.data?.observation_count ?? "—"}</b></span><span>Analyzed <b>{trend.data?.analyzed_observation_count ?? "—"}</b></span><span>Anomalies <b>{trend.data?.anomaly_count ?? "—"}</b></span></div></div>}

      {!id ? <EmptyState title="Select a water body" text="Choose a water body above to load its historical analysis." icon={<History size={20} />} /> :
        <div className="history-grid">
          <section className="panel history-chart-panel">
            <div className="panel-header"><div><div className="panel-kicker">TREND</div><div className="panel-title">{metric === "anomaly_score" ? "Anomaly score" : metric === "chlorophyll" ? "Chlorophyll indicator" : "Turbidity"}</div></div><div className="segmented">{([["anomaly_score","Anomaly"],["turbidity","Turbidity"],["chlorophyll","Chlorophyll"]] as const).map(([key,label]) => <button key={key} className={metric === key ? "active" : ""} onClick={() => setMetric(key)}>{label}</button>)}</div></div>
            {trend.loading ? <div className="chart-loading"><div className="skeleton skeleton-full" /></div> : trend.error ? <ErrorState message={trend.error} /> : trend.data && <TrendChart response={trend.data} metric={metric} />}
          </section>

          <section className="panel">
            <div className="panel-header"><div><div className="panel-kicker">COMPARISON</div><div className="panel-title">Earlier vs latest</div></div></div>
            {comparison.loading ? <LoadingRows count={4} /> : comparison.error ? <ErrorState message={comparison.error} /> : comparison.data && <ComparisonView response={comparison.data} />}
          </section>

          <section className="panel">
            <div className="panel-header"><div><div className="panel-kicker">ANOMALY HISTORY</div><div className="panel-title">Flagged observations</div></div><span className="count-pill">{anomalies.data?.anomaly_count ?? 0}</span></div>
            {anomalies.loading ? <LoadingRows count={4} /> : anomalies.error ? <ErrorState message={anomalies.error} /> : anomalies.data?.anomalies.length ? <div className="anomaly-history">{anomalies.data.anomalies.map((item) => <div className="anomaly-card" key={item.analysis_id}><div className="anomaly-date">{formatDate(item.observation_date)}</div><div className="anomaly-head"><span className={anomalyClass(true)}><AlertTriangle size={13} /> Detected</span><strong>Score {numberOrDash(item.anomaly_score)}</strong><span>{percentOrDash(item.confidence)} confidence</span></div><div className="anomaly-evidence">{item.evidence.map((evidence, index) => <span key={index}>{evidence}</span>)}</div></div>)}</div> : <EmptyState title="No anomalies" text="No anomaly records matched the selected date range." icon={<CheckCircle2 size={20} />} />}
          </section>

          <section className="panel">
            <div className="panel-header"><div><div className="panel-kicker">TIMELINE</div><div className="panel-title">Observation timeline</div></div><span className="table-note">{timeline.data?.length ?? 0} entries</span></div>
            {timeline.loading ? <LoadingRows count={7} /> : timeline.error ? <ErrorState message={timeline.error} /> : timeline.data?.length ? <div className="table-scroll"><table><thead><tr><th>Date</th><th>Satellite</th><th>Scene</th><th>Turbidity</th><th>Chlorophyll</th><th>Anomaly</th><th>Confidence</th></tr></thead><tbody>{timeline.data.map((entry: any) => <tr key={entry.observation_id}><td>{formatDateShort(entry.observation_date)}</td><td>{entry.satellite}</td><td className="mono">{entry.scene_id}</td><td>{numberOrDash(entry.turbidity)}</td><td>{numberOrDash(entry.chlorophyll)}</td><td>{entry.anomaly_detected ? <span className="severity high">Detected</span> : "No"}</td><td>{percentOrDash(entry.confidence)}</td></tr>)}</tbody></table></div> : <EmptyState title="No timeline rows" text="The timeline endpoint returned no observations." icon={<History size={20} />} />}
          </section>
        </div>}
    </div>
  );
}

function ObservationsPage() {
  const [searchParams] = useSearchParams();
  const initialWaterBody = Number(searchParams.get("waterBody")) || "";
  const waterBodies = useAsync(() => getWaterBodies(), []);
  const [waterBodyId, setWaterBodyId] = useState<number | "">(initialWaterBody);
  const observations = useAsync(() => getSatelliteObservations(waterBodyId === "" ? undefined : waterBodyId), [waterBodyId]);
  const [selected, setSelected] = useState<SatelliteObservation | null>(null);
  const latestAnalysis = useAsync(() => selected ? getAnalysisForObservationSafe(selected.id) : Promise.resolve(null), [selected?.id]);

  return (
    <div>
      <PageHeader eyebrow="SATELLITE OBSERVATIONS" title="Observations" text="Inspect scene identifiers, acquisition dates, cloud coverage, quality scores, source links, and related analysis." />
      <div className="filter-bar"><label className="field wide"><span>Water body</span><select value={waterBodyId} onChange={(e) => setWaterBodyId(e.target.value ? Number(e.target.value) : "")}><option value="">All water bodies</option>{(waterBodies.data ?? []).map((wb) => <option key={wb.id} value={wb.id}>{wb.name}</option>)}</select></label><div className="filter-summary"><Satellite size={14} /> {observations.data?.length ?? "—"} observations</div></div>

      <div className="observations-layout">
        <section className="panel">
          <div className="panel-header"><div><div className="panel-kicker">SCENE REGISTRY</div><div className="panel-title">Satellite observations</div></div><div className="table-note">GET /satellite-observations</div></div>
          {observations.loading ? <LoadingRows count={7} /> : observations.error ? <ErrorState message={observations.error} /> : observations.data?.length === 0 ? <EmptyState title="No observations" text="No satellite scenes match the selected water body." icon={<Satellite size={20} />} /> :
            <div className="table-scroll"><table><thead><tr><th>Date</th><th>Water body</th><th>Satellite</th><th>Scene ID</th><th>Cloud</th><th>Quality</th><th></th></tr></thead><tbody>{observations.data.map((observation) => <tr className={selected?.id === observation.id ? "selected-row" : ""} key={observation.id}><td>{formatDateShort(observation.observation_date)}</td><td>{waterBodies.data?.find((wb) => wb.id === observation.water_body_id)?.name ?? `#${observation.water_body_id}`}</td><td>{observation.satellite}</td><td className="mono">{observation.scene_id}</td><td>{observation.cloud_percentage == null ? "—" : `${observation.cloud_percentage.toFixed(1)}%`}</td><td>{numberOrDash(observation.quality_score)}</td><td><button className="icon-button" onClick={() => setSelected(observation)}><ChevronRight size={15} /></button></td></tr>)}</tbody></table></div>}
        </section>

        <aside className="panel observation-detail">
          {!selected ? <EmptyState title="Select an observation" text="Open a scene row to inspect source metadata and the latest analysis linked to it." icon={<Satellite size={20} />} /> :
            <><div className="panel-header"><div><div className="panel-kicker">SCENE DETAIL • #{selected.id}</div><div className="panel-title">{selected.scene_id}</div></div><button className="icon-button" onClick={() => setSelected(null)}><X size={15} /></button></div>
            <div className="detail-list"><div className="detail-row"><span>Satellite</span><strong>{selected.satellite}</strong></div><div className="detail-row"><span>Observation date</span><strong>{formatDate(selected.observation_date)}</strong></div><div className="detail-row"><span>Cloud percentage</span><strong>{selected.cloud_percentage == null ? "—" : `${selected.cloud_percentage.toFixed(1)}%`}</strong></div><div className="detail-row"><span>Quality score</span><strong>{numberOrDash(selected.quality_score)}</strong></div>{selected.source_url && <a className="detail-link" href={selected.source_url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open source scene</a>}</div>
            {selected.observation_metadata && <details className="metadata-box" open><summary>Metadata</summary><pre>{JSON.stringify(selected.observation_metadata, null, 2)}</pre></details>}
            <div className="subpanel"><div className="panel-kicker">LATEST LINKED ANALYSIS</div>{latestAnalysis.loading ? <LoadingRows count={2} /> : latestAnalysis.error ? <div className="muted-block">{latestAnalysis.error}</div> : !latestAnalysis.data ? <EmptyState title="No analysis linked" text="No latest analysis result was returned for this observation." icon={<BarChart3 size={18} />} /> : <div className="mini-metrics"><MetricCard label="Anomaly score" value={numberOrDash(latestAnalysis.data.analysis_data.anomaly_score)} note={latestAnalysis.data.analysis_data.anomaly_detected ? "Detected" : "Not detected"} status={latestAnalysis.data.analysis_data.anomaly_detected ? "alert" : "success"} /><MetricCard label="Confidence" value={percentOrDash(latestAnalysis.data.analysis_data.confidence)} note="Analysis confidence" /><MetricCard label="Model" value={latestAnalysis.data.model_name} note={latestAnalysis.data.model_version ?? "Version not supplied"} /></div>}</div>
            </>}
        </aside>
      </div>
    </div>
  );
}

async function getAnalysisForObservationSafe(id: number): Promise<AnalysisResult | null> {
  try {
    return await getAnalysisResults(id).then((items) => items[0] ?? null);
  } catch {
    try {
      const { getLatestAnalysisForObservation } = await import("./api");
      return await getLatestAnalysisForObservation(id);
    } catch {
      return null;
    }
  }
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  );
}
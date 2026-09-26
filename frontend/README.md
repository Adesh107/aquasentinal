# AquaSentinel Frontend

React + TypeScript + Vite dashboard for the AquaSentinel FastAPI backend.

## Run locally

1. Start the existing FastAPI backend on `http://127.0.0.1:8000`.
2. From this directory, install dependencies:
   `npm install`
3. Copy `.env.example` to `.env` if you need a different API base URL.
4. Start the dashboard:
   `npm run dev`

The dashboard listens on `http://127.0.0.1:5173` by default.

## Backend features covered

The frontend integrates the backend monitoring surface for:
- water bodies, filters, nearby search, and geometry
- satellite observations and source metadata
- analysis results and latest-analysis lookup
- alert filters, detail, explanation, and affected-region geometry
- water-body timeline, trend, comparison, and anomaly history
- backend connection status

The API client also contains request wrappers for the backend POST/PATCH/DELETE operations used by ingestion or administration workflows, but the hackathon monitoring UI keeps those writes backend/pipeline-owned rather than exposing unsafe data-entry controls on the main dashboard.

Scientific display rule: values are shown exactly as reported by the API. The UI does not invent units, measurements, or lab-grade interpretations.
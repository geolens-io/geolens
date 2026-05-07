# GeoLens Frontend

The GeoLens frontend is a React 19 + Vite + TypeScript application. It powers the catalog, dataset detail, map builder, and admin surfaces. MapLibre GL v5 (via `@vis.gl/react-maplibre` v8) renders maps; TanStack Query manages server state; Tailwind CSS handles styling.

For installation, environment configuration, and running the full stack with Docker Compose, see the repository root [README.md](../README.md). For contributing guidelines and development setup, see [.github/CONTRIBUTING.md](../.github/CONTRIBUTING.md).

## Local Development

Once the stack is running (`docker compose up -d` from the repo root), Vite dev mode is hot-reloaded inside the `frontend` container at http://localhost:8080. To run scripts directly on the host:

```bash
cd frontend
npm install        # one-time
npm run dev        # Vite dev server (port 5173 inside Docker; 8080 via the proxy)
npm run test       # Vitest test suite
npm run lint       # ESLint
npm run build      # Production build (tsc -b && vite build)
```

## Layout

- `src/components/` — feature-scoped UI components (catalog, dataset, builder, admin, shared).
- `src/api/` — typed API client wrappers around the auto-generated `@geolens/sdk`.
- `src/hooks/` — TanStack Query hooks and store subscriptions.
- `src/stores/` — global Zustand stores (auth, theme, search, drawing).
- `src/i18n/` — translation files (en/es/fr/de).
- `src/lib/` — utilities (basemap helpers, formatting, validation).

## Documentation

Developer-facing docs that don't fit the public README live under `frontend/docs/` (e.g., custom map widgets in [`frontend/docs/widgets.md`](docs/widgets.md), translation workflow in [`frontend/docs/i18n.md`](docs/i18n.md)).

For the public-facing user, admin, and API documentation, visit [docs.getgeolens.com](https://docs.getgeolens.com).

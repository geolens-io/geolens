# GeoLens OGC API Postman Collection

Import `geolens-ogc-api.postman_collection.json` into Postman, then set:

- `baseUrl`: `http://localhost:8080/api` for the Docker Compose frontend proxy, or `http://localhost:8001` when calling the API port from `.env.example` directly.
- `datasetId`: a dataset UUID from the `List collections` response.

The collection covers:

- OGC landing page
- OGC collections list
- OGC API Features items query with `bbox`
- OGC API Records search over the `datasets` collection

No tokens or secrets are stored in the collection. Public records work anonymously; private records require adding your normal `Authorization` or `X-API-Key` header in Postman.

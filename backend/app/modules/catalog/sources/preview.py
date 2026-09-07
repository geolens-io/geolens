"""Remote service layer preview via ogrinfo."""

import asyncio
import json
import os
import time
from typing import NamedTuple
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import structlog
from fastapi import HTTPException, status

from app.core.runtime.staging import GDAL_HEADER_FILE_REDIRECT_ENV, gdal_header_dir
from app.core.service_tokens import (
    ServiceCredential,
    build_credential_header,
    credential_header_line,
)
from app.core.url_redaction import redact_url_credentials, scrub_secret_value
from app.platform.extensions import get_catalog_port
from app.platform.gdal_env import gdal_service_safe_env
from app.platform.service_auth import credential_input_rejection
from app.core.config import settings
from app.core.runtime.staging import ensure_staging_ready
from app.platform.service_items import (
    ItemFetchFailedError,
    materialise_oapif_items,
)
from app.platform.service_endpoints import (
    CrossOriginEndpointError,
    EndpointCheckFailedError,
    assert_endpoints_stay_on_origin,
    gdal_transport_env,
    require_wfs_layer,
)

_SUBPROCESS_FLOOR_SECONDS = 1.0

logger = structlog.stdlib.get_logger(__name__)
IngestionError = get_catalog_port().ingestion_error_class()


def _encode_url_for_gdal(url: str) -> str:
    """Percent-encode URL paths so GDAL/libcurl accepts ArcGIS service names."""
    parts = urlsplit(url)
    encoded_path = quote(parts.path, safe="/%:@!$&'()*+,;=")
    # fix(#1770): caller's own submitted URL, not a third-party href;
    # bounded by request-body size limits and Pydantic validation.
    pairs = parse_qsl(parts.query, keep_blank_values=True)  # parse_qs: unbounded
    encoded_query = urlencode(pairs)
    return urlunsplit(
        (parts.scheme, parts.netloc, encoded_path, encoded_query, parts.fragment)
    )


# fix(#1746): prefix selects the auth format since run_service_preview
# holds a composed GDAL source string, not a stored format.
_GDAL_SOURCE_FORMATS = {"WFS:": "wfs", "OAPIF:": "ogcapi_features"}


class _Localised(NamedTuple):
    """What to run ogrinfo against, and what to report regardless of it.

    fix(#1746): reported_name/total must NOT come from ogrinfo — pointed
    at a scratch file, the GeoJSON driver reports the temp filename and
    sample count instead of the real collection name/total.
    """

    gdal_source: str
    layer_name: str
    credential: "ServiceCredential | None"
    items_path: str | None
    reported_name: str | None
    total: int | None


async def _localise_protected_oapif(
    gdal_source: str,
    layer_name: str,
    credential: "ServiceCredential | None",
    sample_limit: int,
    deadline: float,
) -> _Localised:
    """Read a protected OGC API collection locally, and describe the file.

    fix(#1746): GDAL_HTTP_HEADER_FILE is process-global and OAPIF paging
    follows a `next` link the origin chooses, so a same-origin first page
    could hand the credential to an origin named on page two — GDAL 3.10.3
    has no way to scope it (measured, see `platform/service_items`). Pages
    are fetched with the bounded client, streamed to a local file, and
    ogrinfo reads that instead. WFS pages by `startIndex` against the
    validated capabilities endpoint and ignores `next`, so it is left alone.

    Returns what to run ogrinfo against, the file to delete afterwards, and
    the name/total to report instead of trusting ogrinfo.
    """
    if credential is None or not gdal_source.startswith("OAPIF:"):
        return _Localised(gdal_source, layer_name, credential, None, None, None)
    try:
        extract = await materialise_oapif_items(
            _service_url(gdal_source),
            layer_name,
            credential_line=credential_header_line(
                _required_pair(build_credential_header(credential))
            ),
            staging_dir=ensure_staging_ready(settings.upload_staging_dir),
            feature_limit=sample_limit,
            # fix(#1746): the preview's budget covers the page
            # walk as well as ogrinfo now. It used to run before the clock
            # started, and the client's timeout is per inactivity, so a service
            # answering slowly forever held the API request open indefinitely.
            deadline=deadline,
        )
    except ItemFetchFailedError as exc:
        # Same coded 422 the description check gives: the URL's collection
        # can't be read safely, and the field to change is the URL.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": exc.policy, "field": exc.field},
        ) from None
    # A local file, no credential anywhere in what follows. layer_name is
    # dropped (GeoJSON driver has exactly one layer); the collection the
    # caller asked for is still what gets reported.
    return _Localised(extract.path, "", None, extract.path, layer_name, extract.total)


def _remove_quietly(path: str | None) -> None:
    """Unlink a temp file; "already gone" counts as success.

    Covers the 0600 credential header and the local OAPIF copy — a SIGKILL
    between the two is what the staging/header sweeps reclaim.
    """
    if path is None:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _required_pair(pair: tuple[str, str] | None) -> tuple[str, str]:
    if pair is None:  # pragma: no cover - unreachable from the OAPIF branch
        raise IngestionError("no credential header could be composed")
    return pair


def _gdal_source_format(gdal_source: str) -> str | None:
    for prefix, service_format in _GDAL_SOURCE_FORMATS.items():
        if gdal_source.startswith(prefix):
            return service_format
    return None


def _service_url(gdal_source: str) -> str:
    for prefix in _GDAL_SOURCE_FORMATS:
        if gdal_source.startswith(prefix):
            return gdal_source[len(prefix) :]
    return gdal_source


def build_gdal_source(
    service_type: str,
    base_url: str,
    layer_name: str,
    layer_id: int | str | None = None,
    token: str | None = None,
    order_field: str | None = "OBJECTID",
    result_limit: int | None = None,
    result_offset: int | None = None,
) -> tuple[str, str]:
    """Construct a GDAL-prefixed source string for a remote service.

    Returns:
        Tuple of (gdal_source, layer_name) where layer_name may be empty
        for drivers that embed the layer in the source URL.
    """
    if service_type.startswith("WFS"):
        return (f"WFS:{base_url}", layer_name)
    elif service_type.startswith("ArcGIS"):
        if layer_id is None:
            raise ValueError("ArcGIS layer preview requires a layer ID")
        safe_base_url = _encode_url_for_gdal(base_url.rstrip("/"))
        safe_layer_id = quote(str(layer_id).strip("/"), safe="")
        # fix(#1359): omitting outFields returns only the display field,
        # dropping every other column. urlencode renders `*` as `%2A`,
        # which ArcGIS decodes back correctly.
        params: dict[str, str | int] = {
            "f": "json",
            "where": "1=1",
            "outFields": "*",
        }
        if order_field:
            params["orderByFields"] = f"{order_field} ASC"
        if result_limit is not None:
            params["resultRecordCount"] = result_limit
        if result_offset is not None:
            params["resultOffset"] = result_offset
        # feat(C2): kept as a query param — GDAL only reads credentials from
        # GDAL_HTTP_HEADER_FILE, whose charset rejects the `+`/`/` a real
        # ArcGIS token can contain. Exposure (argv, GDAL error text) is
        # bounded: run_ogr2ogr_service redacts it and #1753 purges the job row.
        if token:
            params["token"] = token
        query_url = f"{safe_base_url}/{safe_layer_id}/query?{urlencode(params)}"
        return (f"ESRIJSON:{query_url}", "")
    elif service_type.startswith("OGC API"):
        return (f"OAPIF:{base_url}", layer_name)
    else:
        raise ValueError(f"Unsupported service type: {service_type}")


async def run_service_preview(
    gdal_source: str,
    layer_name: str,
    sample_limit: int = 5,
    timeout: float = 30.0,
    credential: ServiceCredential | None = None,
) -> dict:
    """Run ogrinfo against a remote service to get layer metadata and sample rows.

    credential is ignored for ArcGIS (token is already in gdal_source's query
    string); for WFS/OGC API Features it becomes the one line of a 0600
    GDAL_HTTP_HEADER_FILE.

    Returns a dict with srid, geometry_type, layer_name, feature_count,
    columns, sample_rows.
    """
    empty_fallback: dict = {
        "srid": None,
        "geometry_type": None,
        "layer_name": layer_name,
        "feature_count": None,
        "columns": [],
        "sample_rows": [],
    }

    # fix(#1746): protected OAPIF collections are localised here, not
    # read by GDAL directly — see _localise_protected_oapif for why.
    deadline = time.monotonic() + timeout
    localised = await _localise_protected_oapif(
        gdal_source, layer_name, credential, sample_limit, deadline
    )
    gdal_source = localised.gdal_source
    layer_name = localised.layer_name
    credential = localised.credential
    items_path = localised.items_path
    # fix(#1846, GHSA-hrf5-v3cq-frx5): service branch driver is pinned by the
    # WFS:/OAPIF:/ESRIJSON: prefix; localised branch swaps in a bare staging
    # path, so `-if GeoJSON` is forced — _walk_pages guarantees those bytes
    # really are JSON, so naming the driver here is a true claim, not a guess.
    driver_args = ["-if", "GeoJSON"] if items_path is not None else []
    cmd = [
        "ogrinfo",
        "-json",
        "-features",
        "-limit",
        str(sample_limit),
        "--config",
        "GDAL_HTTP_TIMEOUT",
        "60",
        *driver_args,
        gdal_source,
    ]
    if layer_name:
        cmd.append(layer_name)

    logger.info(
        "running ogrinfo for service preview",
        gdal_source=redact_url_credentials(gdal_source),
        layer_name=layer_name,
    )

    header_file_path: str | None = None
    # fix(#1746): kept in scope for the finally/error paths below —
    # pattern-based redactors can't see a credential in a header line, only
    # the exact value can scrub an echoed one.
    header_line: str | None = None
    try:
        # fix(#937): GDAL_HTTP_FOLLOWLOCATION is not a real GDAL option and
        # never stopped a redirect — never re-add it. SSRF defense is
        # validate_url_for_ssrf at submission; libcurl follows redirects
        # unconditionally after that, bounded operationally (egress firewall).
        # fix(#1857): SERVICE variant — this branch reads WFS/OAPIF,
        # which the vector variant skips.
        env = gdal_service_safe_env()
        pair: tuple[str, str] | None = None
        if credential is not None and (
            gdal_source.startswith("WFS:") or gdal_source.startswith("OAPIF:")
        ):
            # fix(#1746): judge inputs before composing the header line —
            # judging the composed line would reject every basic credential
            # (it contains a space and colon), and would let a WFS token with
            # `+`/`/` preview clean then fail at commit.
            rejection = credential_input_rejection(credential)
            if rejection is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "code": "invalid_service_token",
                        "message": rejection,
                    },
                )

            pair = build_credential_header(credential)

        if pair is not None:
            # fix(#1746): checked before the header file exists, since
            # GDAL applies it to endpoints the service's own description
            # advertises. Checked again in the worker: the document can
            # change between preview and the import it leads to.
            try:
                # fix(#1828): a credentialed WFS never reaches GDAL without a
                # layer, since GDAL opened layerless reads every layer's schema.
                require_wfs_layer(
                    layer_name,
                    service_format=_gdal_source_format(gdal_source),
                    credential_line=credential_header_line(pair),
                )
                await assert_endpoints_stay_on_origin(
                    _service_url(gdal_source),
                    service_format=_gdal_source_format(gdal_source),
                    # fix(#1746): same line the worker will hand GDAL, so
                    # a protected service answers with the document GDAL will
                    # act on rather than a 401.
                    credential_line=credential_header_line(pair),
                    collection=layer_name or None,
                    # fix(#1746): inside the preview's budget — the
                    # client's per-inactivity timeout let a service trickling
                    # a 32 MiB doc hold the request open before ogrinfo ran.
                    deadline=deadline,
                )
            except (CrossOriginEndpointError, EndpointCheckFailedError) as exc:
                # Coded 422, not the 502 the broad handler upstairs would
                # make of it: names the field to change on the caller's URL.
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "code": exc.code,
                        "message": exc.policy,
                        "field": exc.field,
                    },
                ) from None

            # SEC-021: mirror the ogr2ogr commit path (IA-P1-06 / SEC-FU-04).
            # GDAL_HTTP_HEADERS would leak the credential via subprocess env
            # (/proc/<pid>/environ) and let a CR/LF inject outbound HTTP
            # headers under libcurl. Use a 0600 GDAL_HTTP_HEADER_FILE instead,
            # so the env var carries a path, not the secret; unlinked in the
            # finally below.
            #
            # fix(#1746): the line comes from the shared joiner alone — no
            # prefix composed here, so a finished basic credential can't
            # collide with a hardcoded "Authorization: Bearer " prefix and
            # produce a working-looking string that 401s at the origin.
            header_line = credential_header_line(pair)
            import tempfile

            # fix(#1746): name the directory explicitly, not the container
            # tmpfs default — gdal_header_dir() is 0700 under /tmp (private
            # to this container, gone on restart, swept at boot and on the
            # API's periodic cadence), so a header orphaned by a SIGKILL
            # can't land in the staging volume that gets tarred into backups.
            fd, header_file_path = tempfile.mkstemp(
                prefix="gdal_auth_",
                suffix=".hdr",
                dir=gdal_header_dir(),
            )
            try:
                os.write(fd, f"{header_line}\n".encode("ascii"))
            finally:
                os.close(fd)
            os.chmod(header_file_path, 0o600)
            env["GDAL_HTTP_HEADER_FILE"] = header_file_path
            env.update(gdal_transport_env(_gdal_source_format(gdal_source)))
            # Plan rule A: GDAL forwards non-Authorization headers verbatim
            # across hosts, so a service-chosen API key is redirect-exposed
            # here and can't be protected from inside (AGENTS.md Rule 2).
            # IF_SAME_HOST not NO: a same-host canonical redirect (e.g. a
            # trailing slash) must keep the credential or the service 401s.
            env.update(GDAL_HEADER_FILE_REDIRECT_ENV)

        # fix(#1746): computed here so it accounts for budget already
        # spent (page walk, endpoint check). Floored so a preflight that used
        # the whole budget still fails via the ordinary timeout, not an
        # arithmetic edge.
        timeout = max(deadline - time.monotonic(), _SUBPROCESS_FLOOR_SECONDS)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            logger.warning(
                "ogrinfo timed out for service preview",
                gdal_source=redact_url_credentials(gdal_source),
                layer_name=layer_name,
                timeout=timeout,
            )
            # A timeout is a real failure, not a genuinely-empty layer — raise
            # so the router surfaces a 502 instead of a fake-success preview
            # with zero columns. empty_fallback is for zero-feature layers only.
            raise IngestionError(
                f"ogrinfo timed out after {timeout:.0f}s for service preview"
            ) from exc
    finally:
        # Both are removed on every exit, success or not: one holds a
        # credential and the other holds data read with it.
        _remove_quietly(items_path)
        _remove_quietly(header_file_path)

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "unknown error"
        # fix(#1746): a credential GDAL echoes back in stderr prose isn't a
        # URL shape or a KEY name, so redact_url_credentials and the log
        # processor both miss it. scrub_secret_value holds the exact value
        # instead, applied before the log and the exception are built so
        # every downstream reader sees the same scrubbed text.
        safe_error_msg = scrub_secret_value(
            redact_url_credentials(error_msg), header_line
        )
        logger.error(
            "ogrinfo failed for service preview",
            gdal_source=redact_url_credentials(gdal_source),
            returncode=proc.returncode,
            stderr=safe_error_msg,
        )
        raise IngestionError(f"ogrinfo failed: {safe_error_msg}")

    try:
        data = json.loads(stdout.decode())
    except (ValueError, UnicodeDecodeError):
        # fix(#1746): a JSONDecodeError carries the document it failed to
        # parse, which is GDAL output too. This refusal names no part of it;
        # `from None` keeps the chained original from carrying it either.
        logger.error(
            "ogrinfo returned unreadable output for service preview",
            gdal_source=redact_url_credentials(gdal_source),
            layer_name=layer_name,
        )
        raise IngestionError(
            "ogrinfo returned output that could not be read as JSON"
        ) from None

    layers = data.get("layers", [])
    if not layers:
        logger.warning(
            "ogrinfo returned no layers",
            gdal_source=redact_url_credentials(gdal_source),
        )
        return empty_fallback

    layer = layers[0]

    columns = [{"name": f["name"], "type": f["type"]} for f in layer.get("fields", [])]

    sample_rows = [feat.get("properties", {}) for feat in layer.get("features", [])]

    geom_fields = layer.get("geometryFields", [])
    geometry_type = None
    coord_system = layer.get("coordinateSystem", {})
    if geom_fields:
        geometry_type = geom_fields[0].get("type")
        if not coord_system:
            coord_system = geom_fields[0].get("coordinateSystem", {})

    srid = get_catalog_port().extract_srid_from_json(coord_system or {})

    result = {
        "srid": srid,
        "geometry_type": geometry_type,
        # fix(#1746): for a localised collection these come from the
        # request/service, not ogrinfo, which is describing a scratch file.
        "layer_name": localised.reported_name or layer.get("name", layer_name),
        "feature_count": (
            localised.total
            if localised.reported_name is not None
            else layer.get("featureCount")
        ),
        "columns": columns,
        "sample_rows": sample_rows,
    }

    logger.info(
        "service preview complete",
        gdal_source=redact_url_credentials(gdal_source),
        layer_name=result["layer_name"],
        feature_count=result["feature_count"],
        column_count=len(columns),
        sample_count=len(sample_rows),
    )

    return result

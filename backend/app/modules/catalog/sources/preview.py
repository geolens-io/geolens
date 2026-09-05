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
)

_SUBPROCESS_FLOOR_SECONDS = 1.0

logger = structlog.stdlib.get_logger(__name__)
IngestionError = get_catalog_port().ingestion_error_class()


def _encode_url_for_gdal(url: str) -> str:
    """Percent-encode URL paths so GDAL/libcurl accepts ArcGIS service names."""
    parts = urlsplit(url)
    encoded_path = quote(parts.path, safe="/%:@!$&'()*+,;=")
    # fix(#1770 round 47 P1 class): the caller's OWN submitted service URL,
    # not a service-advertised href read out of a third-party response --
    # different threat model, already bounded by request-body size limits
    # and Pydantic field validation on the way in.
    pairs = parse_qsl(parts.query, keep_blank_values=True)  # parse_qs: unbounded
    encoded_query = urlencode(pairs)
    return urlunsplit(
        (parts.scheme, parts.netloc, encoded_path, encoded_query, parts.fragment)
    )


# fix(#1746 B2b review r13): the two header-auth prefixes, and the bare URL
# behind them. `run_service_preview` holds a composed GDAL source string
# rather than a stored format, which is why the prefix is the selector here,
# exactly as it already is for deciding whether to write a header file at all.
_GDAL_SOURCE_FORMATS = {"WFS:": "wfs", "OAPIF:": "ogcapi_features"}


class _Localised(NamedTuple):
    """What to run ogrinfo against, and what to report regardless of it.

    fix(#1746 B2b review r24): ``reported_name`` and ``total`` do not come from
    ogrinfo and must not. Pointed at a scratch file with no layer argument, the
    GeoJSON driver answers with the temp file's name and with the number of
    features in the sample, so the user saw `oapif_items_xxxx` where their
    collection should be and a row count of `sample_limit`.
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

    fix(#1746 B2b review r16): its pages choose the next one, GDAL follows that
    link, and `GDAL_HTTP_HEADER_FILE` applies to every request the process
    makes, so a collection whose first page is same-origin can hand the
    credential to any origin it names on page two. GDAL 3.10.3 offers no way to
    scope the header to one origin, which was measured rather than assumed (see
    `platform/service_items`), so the credential is kept out of GDAL entirely
    here: the pages are fetched with the bounded client, streamed to a local
    file, and ogrinfo is pointed at that.

    WFS needs none of this and is left alone. Its driver pages by `startIndex`
    against the endpoint the capabilities advertise, which is the endpoint the
    description check validates, and it ignores a `next` attribute outright.

    Returns the source, layer and credential to use from here, the file to
    delete afterwards, and the two things the caller must report from here
    rather than from ogrinfo.
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
            # fix(#1746 B2b review r17): the preview's budget covers the page
            # walk as well as ogrinfo now. It used to run before the clock
            # started, and the client's timeout is per inactivity, so a service
            # answering slowly forever held the API request open indefinitely.
            deadline=deadline,
        )
    except ItemFetchFailedError as exc:
        # The same coded answer the description check gives, for the same
        # reason: the caller named a URL whose collection cannot be read
        # safely, and the field to change is the URL.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": exc.policy, "field": exc.field},
        ) from None
    # A local file, with no credential anywhere in what follows. The layer
    # argument is dropped because the GeoJSON driver has exactly one layer, but
    # the collection the caller asked for is what gets reported.
    return _Localised(extract.path, "", None, extract.path, layer_name, extract.total)


def _remove_quietly(path: str | None) -> None:
    """Unlink a temp file, treating "already gone" as the outcome it wanted.

    Two of these exist on the preview path and both hold something that should
    not outlive it: the 0600 credential header, and the local copy of a
    protected collection. A SIGKILL between the two is what the staging and
    header sweeps reclaim.
    """
    if path is None:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _required_pair(pair: tuple[str, str] | None) -> tuple[str, str]:
    """The builder's pair, where the caller has established there is one.

    `build_credential_header` answers None for a format that carries no header,
    and this branch runs only for `OAPIF:`, which is one of the two that do.
    """
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
        # fix(#1359): a /query with no outFields returns the layer's display
        # field alone, so the import landed geometry plus ONE attribute column
        # and dropped every other field. The preview reads the layer's ?f=json
        # field list and therefore promised columns this fetch never asked
        # for. urlencode renders the value as `outFields=%2A`, which ArcGIS
        # decodes back to `*`.
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
        # feat(C2): deliberately still the query form, and the one ArcGIS
        # transport lane C2 did NOT move. The httpx adapter sends
        # ``Authorization: Bearer`` now, but GDAL reads a credential only from
        # ``GDAL_HTTP_HEADER_FILE``, which is process-global (measured for
        # #1770 and recorded in ``platform/service_items``) and whose writer
        # holds every line to ``HEADER_TOKEN_CHARSET``. An ArcGIS token
        # legitimately contains ``+`` or ``/``, which that charset refuses, so
        # moving this path would mean either widening the base64url rule that
        # exists to stop header smuggling into libcurl, or refusing tokens that
        # work today. The exposure this leaves -- the token in the subprocess
        # argv and in GDAL's error text -- is bounded where it lands:
        # ``run_ogr2ogr_service`` redacts before the text becomes an exception,
        # and #1753 purges the job row.
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

    Args:
        gdal_source: GDAL-prefixed source string (e.g. "WFS:https://..." or "ESRIJSON:https://...")
        layer_name: Layer name to query (empty string for drivers that embed layer in URL)
        sample_limit: Maximum number of sample features to retrieve
        timeout: Seconds before killing the subprocess
        credential: What to authenticate with, or None. For an ArcGIS source
            the credential is already in ``gdal_source``'s query string and
            this is ignored; for WFS and OGC API Features it becomes the one
            line of a 0600 ``GDAL_HTTP_HEADER_FILE``.

    Returns:
        Dict with keys: srid, geometry_type, layer_name, feature_count, columns, sample_rows
    """
    empty_fallback: dict = {
        "srid": None,
        "geometry_type": None,
        "layer_name": layer_name,
        "feature_count": None,
        "columns": [],
        "sample_rows": [],
    }

    # fix(#1746 B2b review r16): a protected OGC API collection is read HERE,
    # not by GDAL. Its pages choose the next one, GDAL follows that link, and
    # `GDAL_HTTP_HEADER_FILE` applies to every request the process makes, so a
    # collection whose first page is same-origin can hand the credential to any
    # origin it names on page two. GDAL 3.10.3 has no way to scope the header to
    # one origin, which was measured rather than assumed (see
    # `platform/service_items`), so the credential is kept out of GDAL entirely
    # for this path: the pages are fetched with the bounded client, streamed to
    # a local file, and ogrinfo is pointed at that. WFS needs none of this; its
    # driver pages by startIndex against the endpoint the capabilities
    # advertise, which the description check validates.
    deadline = time.monotonic() + timeout
    localised = await _localise_protected_oapif(
        gdal_source, layer_name, credential, sample_limit, deadline
    )
    gdal_source = localised.gdal_source
    layer_name = localised.layer_name
    credential = localised.credential
    items_path = localised.items_path
    # fix(#1846, GHSA-hrf5-v3cq-frx5): on the service branch the driver is
    # pinned by the WFS:/OAPIF:/ESRIJSON: prefix the source string carries. On
    # the localised branch it is not: `_localise_protected_oapif` swaps the
    # source for a bare local staging path, and a bare path is identified by
    # content like any other file. `_walk_pages` re-encodes every feature into
    # its own FeatureCollection wrapper, so those bytes are always JSON --
    # which makes naming the driver free, and makes the claim true rather than
    # merely true in practice.
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
    # fix(#1746 B2b review r2): kept in scope past the block that composes it,
    # because the failure handling below the `finally` is what needs it. The
    # pattern-based redactors cannot see a credential in a header line, so the
    # exact value is the only thing that can scrub an echo of one.
    header_line: str | None = None
    try:
        # fix(#937): this env used to set GDAL_HTTP_FOLLOWLOCATION=NO as a
        # redirect defense. That is not a GDAL configuration option and never
        # stopped a redirect; do not re-add it. The actual SSRF defense for
        # this user-supplied service URL is validate_url_for_ssrf at
        # submission time; libcurl under GDAL follows redirects
        # unconditionally, so post-validation redirects must be bounded
        # operationally (worker egress firewall).
        # fix(#1857 item 3): the driver clamp this site used to carry a written
        # justification for NOT having. It spawns ogrinfo on a caller-supplied
        # service URL, and several OGR drivers read the document they are
        # handed as instructions naming somewhere else to read from, so the
        # prefix on the source string was the only thing deciding the driver.
        # The service variant specifically: it keeps WFS and OAPIF, which the
        # service branch exists to use, and skips the pointer-following and
        # helper-spawning drivers on both branches. Harmless on the localised
        # branch, whose source is a bare local path already pinned by
        # -if GeoJSON.
        #
        # The helpers used to be unreachable from here, not inapplicable:
        # modules/catalog/ may not import app.processing.* and that is where
        # they lived. They live in app/platform/gdal_env.py now.
        env = gdal_service_safe_env()
        pair: tuple[str, str] | None = None
        if credential is not None and (
            gdal_source.startswith("WFS:") or gdal_source.startswith("OAPIF:")
        ):
            # fix(#1746): the credential policy first, because this branch
            # builds the same header line the commit path builds. Preview used
            # to judge the token by `_validate_safe_token` alone — printable,
            # no whitespace — so a WFS token containing `+` or `/` previewed
            # cleanly and was then refused at commit, or worse, burned its
            # single-use credential and died in the worker. Same 422, same code
            # and same policy-only message the commit doors return: the caller
            # has the credential and can compare it against the rule, and a
            # response must never echo any part of one.
            #
            # fix(#1746 B2b): the inputs are judged, and the line is composed
            # afterwards by the one builder. Judging the composed line instead
            # would reject every basic credential, because a basic line
            # contains a space and a colon.
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
            # fix(#1746 B2b review r13): before the header file exists, because
            # GDAL applies it to the operation endpoints the service's own
            # description advertises, and those are fresh requests no redirect
            # rule can see. Checked again in the worker: the document can
            # change between a preview and the import it leads to.
            try:
                await assert_endpoints_stay_on_origin(
                    _service_url(gdal_source),
                    service_format=_gdal_source_format(gdal_source),
                    # fix(#1746 B2b review r14): the same line the worker will
                    # hand GDAL, so a protected service answers with the
                    # document GDAL will act on rather than a 401. And the
                    # layer being previewed, so the collection actually read is
                    # the one checked rather than whatever fits on page one.
                    credential_line=credential_header_line(pair),
                    collection=layer_name or None,
                    # fix(#1746 B2b review r23): inside the preview's budget.
                    # The client's timeout is per inactivity, so a service
                    # trickling a 32 MiB capabilities document held the request
                    # open indefinitely before ogrinfo had started.
                    deadline=deadline,
                )
            except (CrossOriginEndpointError, EndpointCheckFailedError) as exc:
                # A coded 422, not the 502 the broad handler upstairs would
                # make of it: this is an answer about the URL the caller
                # submitted, and it names the field to change.
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "code": exc.code,
                        "message": exc.policy,
                        "field": exc.field,
                    },
                ) from None

            # SEC-021: mirror the ogr2ogr commit path (IA-P1-06 / SEC-FU-04).
            # Passing the credential via GDAL_HTTP_HEADERS leaks it through the
            # subprocess env (visible in /proc/<pid>/environ for the process
            # lifetime) and lets a CR/LF in it inject arbitrary outbound HTTP
            # headers under libcurl. Hand it to GDAL via a 0600
            # GDAL_HTTP_HEADER_FILE instead, so the env var carries the file
            # PATH and not the secret. The tempfile is unlinked in the finally
            # below.
            #
            # fix(#1746 B2b): the line comes from the shared joiner and this
            # site composes no prefix of its own. It used to write
            # `f"Authorization: Bearer {token}"`, and handing that same line a
            # finished basic credential would have produced
            # `Authorization: Bearer Authorization: Basic <blob>` — a
            # working-looking string that 401s at the origin and reads in a log
            # like a credential problem rather than a bug.
            header_line = credential_header_line(pair)
            import tempfile

            # fix(#1746): name the directory rather than inheriting it.
            # Without `dir=`, where this credential file lands depends on
            # whether the process ran `redirect_tempfile_to_staging`
            # (app/api/main.py, app/platform/jobs/worker.py) AND on that
            # helper's own escape hatch — it silently declines to move
            # `tempfile.tempdir` when the directory is missing.
            #
            # fix(#1746 codex r2): and the directory is the container tmpfs,
            # not the staging volume. Staging is a persistent volume that
            # `scripts/backup-entrypoint.sh` tars every cycle, so a header
            # orphaned by a SIGKILL before the unlink below could be archived
            # into a backup. `gdal_header_dir()` is 0700 under /tmp, which both
            # the api and the worker mount as their own 512m tmpfs: the file is
            # private to this container and gone on restart, and the sweep at
            # boot and on the API's periodic cadence reclaims one that leaks
            # inside a container that keeps running.
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
            # Plan rule A: GDAL forwards `Authorization` only to the host it
            # was given to, and forwards every other header name verbatim even
            # across hosts, so a service-chosen API key is redirect-exposed on
            # this path and cannot be protected from inside (bounded
            # operationally, AGENTS.md Rule 2). The value is stated rather than
            # inherited, and it is IF_SAME_HOST rather than NO: a same-host
            # canonical redirect, such as one adding a trailing slash, must
            # keep the credential or a protected service answers 401.
            env.update(GDAL_HEADER_FILE_REDIRECT_ENV)

        # fix(#1746 B2b review r23): computed HERE rather than earlier, so it
        # accounts for everything that has already spent the budget: the
        # in-process page walk for a protected OGC API collection, and the
        # endpoint check just above. Floored so a preflight that used the whole
        # budget still fails through the ordinary ogrinfo timeout rather than
        # through an arithmetic edge.
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
            # A timeout is a real failure, not a genuinely-empty layer. Raise so
            # the router surfaces a 502 error toast instead of returning a
            # fake-success preview with zero columns (which left the UI showing
            # a spinner then no attributes). empty_fallback is reserved for
            # zero-feature layers only (handled below).
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
        # fix(#1746 B2b review r2): the exact-value scrub the worker task path
        # already applies, brought to the preview path for the same reason.
        # `redact_url_credentials` matches URL shapes and the stdlib log
        # processor matches KEY names, and a credential echoed by the origin
        # arrives as neither: GDAL prints the request it failed on, so an
        # `Authorization: Basic <blob>` or a service-chosen API key can land in
        # stderr as prose. `scrub_secret_value` needs no theory about the shape
        # because it holds the value, and it covers the composed line, the
        # scheme-prefixed half and the bare credential
        # (`_secret_variants`). Applied BEFORE the log and before the exception
        # is constructed, so every downstream reader of either sees the same
        # scrubbed text.
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
        # fix(#1746 B2b review r2): an exit-0 run whose stdout is not the JSON
        # document this asked for used to raise the decoder's own exception,
        # and a JSONDecodeError carries the document that failed to parse.
        # That document is GDAL output too. This refusal says only that the
        # output could not be read, and names no part of it. `from None` so
        # the chained original cannot carry it either.
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
        # fix(#1746 B2b review r24): for a localised collection both of these
        # come from the request and the service rather than from ogrinfo, which
        # is describing a scratch file it was handed. Everywhere else they come
        # from ogrinfo exactly as before.
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

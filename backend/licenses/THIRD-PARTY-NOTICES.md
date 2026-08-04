# Third-party notices — GeoLens backend/worker image

GeoLens itself is licensed under Apache-2.0 (see `LICENSE` and `NOTICE` at the
repository root). This file covers the copyleft-licensed third-party packages
that ship **inside the backend and worker container images** and whose license
obligations attach on distribution. It is not a full dependency inventory: every
other package in the image, and every published GeoLens artifact (the `geolens`
CLI, the Python and TypeScript SDKs, the MCP server, and the frontend bundle),
is permissively licensed and needs no notice beyond the ones its own package
carries.

The license texts referenced below sit next to this file, and the whole
directory lands at `/app/licenses/` in the image.

## psycopg 3.3.4, psycopg-pool 3.3.0 — LGPL-3.0-only

PostgreSQL driver and connection pool. Copyright © The Psycopg Team.
`psycopg-pool` arrives both directly and through `procrastinate[pool]`.

License text: `LGPL-3.0.txt`, plus `GPL-3.0.txt` — LGPL-3.0 is written as a set
of additional permissions on top of GPL-3.0 and incorporates its terms by
reference, so the two must be read together.

GeoLens uses both packages as unmodified libraries through their public Python
API. That is §5 dynamic use: no psycopg source is copied into GeoLens code and
no psycopg source is modified. The obligation is to include these license texts,
say what is used (this section), and not obstruct replacement of the library.

**Replacing the library.** Both are installed as ordinary site-packages in the
image's virtualenv at `/app/.venv/lib/python3.14/site-packages/`. A recipient
may replace either with a modified version of the same major line by installing
over it — for example
`docker run --entrypoint /bin/sh <image> -c "uv pip install --force-reinstall ./my-psycopg"`
in a derived image, or by rebuilding from this repository with the dependency
repinned in `backend/pyproject.toml`. Nothing in the image links psycopg
statically, verifies its contents, or otherwise resists substitution.

## pygeoif 1.6.0 — LGPL-2.1-or-later

Pure-Python geometry primitives. Copyright © 2012–2024 Christian Ledermann.
Reaches the image through `pygeofilter[backend-sqlalchemy]`.

License text: `LGPL-2.1.txt`.

The distributed artifact declares only `License: LGPL` with no version, and its
wheel carries no license file, so the version is taken from the per-module
headers in the shipped source, which are explicit and consistent:

> This library is free software; you can redistribute it and/or modify it under
> the terms of the GNU Lesser General Public License as published by the Free
> Software Foundation; either version 2.1 of the License, or (at your option)
> any later version.

Seven of the eight modules in `pygeoif/` carry that header verbatim; the eighth
(`about.py`) is a version-string stub with no header and no code. Note that the
upstream repository has **no** `LICENSE` file at the `1.6.0` tag — one was added
to the default branch afterwards — so the source headers in the released
artifact are the authoritative statement for this version, not the repository
root. Same dynamic-use analysis and same replacement path as psycopg above.

## text-unidecode 1.3 — dual-licensed; GeoLens elects Artistic-1.0

ASCII transliteration table. Reaches the image through `python-slugify`.

License text: `text-unidecode-LICENSE.txt`, reproduced verbatim from the package
because it states the dual license and contains the Artistic License in full.

The package is offered under **either** GPL (the artifact's classifiers name
both plain GPL and GPLv2+) **or** the Artistic License 1.0.
**GeoLens elects Artistic-1.0.** No GPL obligation attaches to the GeoLens image
on account of this package.

The election is written down here because it cannot be read off the metadata:
`pip` and most automated scanners report the package as "GPL" or surface the GPL
classifiers first, so a scan of the image will keep flagging it. This section is
the answer to that finding.

**Guard:** never enable `python-slugify`'s `[unidecode]` extra. It pulls
`Unidecode`, which is GPL-only, and no election is available there.

## certifi 2026.2.25 — MPL-2.0

Mozilla's CA root certificate bundle. Reaches the image through `httpx`,
`httpcore`, `requests`, `rasterio` and `sentry-sdk` — effectively every
outbound TLS path.

License texts: `MPL-2.0.txt` and `certifi-LICENSE.txt` (the latter also carries
the MPL-1.1/GPL-2.0/LGPL-2.1 tri-license notice that Mozilla attaches to
`ca-bundle.crt` itself).

The package ships unmodified. MPL-2.0 is file-level copyleft: the obligation
attaches to the MPL-licensed files, not to GeoLens code that merely imports
them, and §3.3 explicitly permits distributing a Larger Work under other terms.
Obligations discharged here: the license text is included, the files are
unmodified, and the corresponding source is `certifi==2026.2.25` from PyPI,
identifiable from `/app/uv.lock` and installable with
`uv pip download certifi==2026.2.25 --no-binary :all:`.

## tqdm 4.67.3 — MPL-2.0 AND MIT

Progress-bar library. Reaches the image through `openai`.

License text: `tqdm-LICENCE.txt`, reproduced verbatim because it is what carries
the file-level split — most of the work is MIT, with `MPL-2.0 2015-2026 (c)
Casper da Costa-Luis` covering `*` and specific files listed individually.
`MPL-2.0.txt` holds the referenced MPL text.

Ships unmodified; same MPL-2.0 analysis and same source-availability answer as
certifi above.

## Scope

This file covers the Python distributions installed into the image's virtualenv
(`uv sync --locked --no-dev`), which is where GeoLens's own dependency choices
land. It does not enumerate the Debian packages inherited from the
`python:3.14-slim` base image or installed by the image's `apt-get` layer
(`gdal-bin`, `libexpat1`, `xmlsec1`, and their transitive OS dependencies) —
those carry their own copyright files at `/usr/share/doc/<package>/copyright`
inside the image, which is where Debian policy puts them and where a recipient
or scanner expects to find them.

Regenerating the review after a dependency change: the packages above were found
by walking `importlib.metadata` over the resolved environment and matching
license metadata against the copyleft families (GPL/LGPL/AGPL, MPL, EPL, CDDL),
then confirming each hit against `uv export --no-dev` so dev-only packages are
excluded. Watch for two traps that showed up doing it. Metadata substring
matching false-positives on BSD license *text* — "EXEMPLARY" contains "mpl" —
so read the matched field, do not trust the match. And a package can declare a
copyleft family with no version and no bundled license file, as pygeoif does, in
which case the shipped source headers are the authority.

#!/usr/bin/env python3
"""Backend package restructuring migration tool.

Moves real code from old flat directories to new nested hierarchy,
creates backward-compat shims at old locations, and updates import paths.

Usage:
    python scripts/refactor_migrate.py --wave 1    # Run wave 1
    python scripts/refactor_migrate.py --wave 2    # Run wave 2
    python scripts/refactor_migrate.py --verify    # Verify imports work
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

# Import path replacements for core infrastructure (already moved)
CORE_IMPORT_MAP = {
    "from app.config import": "from app.core.config import",
    "from app.config ": "from app.core.config ",  # bare "from app.config " in some imports
    "from app.database import": "from app.core.db import",
    "from app.dependencies import": "from app.core.dependencies import",
    "from app.logging_config import": "from app.core.logging_config import",
    "from app.public_urls import": "from app.core.public_urls import",
    "from app.edition import": "from app.core.edition import",
    "from app.persistent_config import": "from app.core.persistent_config import",
    "from app.marketplace import": "from app.core.marketplace import",
    "import app.config ": "import app.core.config ",
    "import app.config\n": "import app.core.config\n",
    "import app.database ": "import app.core.db ",
    "import app.database\n": "import app.core.db\n",
}


def update_imports(content: str, extra_map: dict[str, str] | None = None) -> str:
    """Apply import path replacements to file content."""
    result = content
    all_maps = {**CORE_IMPORT_MAP}
    if extra_map:
        all_maps.update(extra_map)
    for old, new in all_maps.items():
        result = result.replace(old, new)
    return result


def make_shim(new_module_path: str, docstring: str = "") -> str:
    """Generate a backward-compat shim file."""
    doc = docstring or f"Compatibility shim — real code moved to {new_module_path}."
    return f'"""{doc}"""\n\nfrom {new_module_path} import *  # noqa: F403\n'


def make_shim_with_all(new_module_path: str, names: list[str], docstring: str = "") -> str:
    """Generate a shim with explicit __all__."""
    doc = docstring or f"Compatibility shim — real code moved to {new_module_path}."
    names_str = ", ".join(f'"{n}"' for n in names)
    imports = ", ".join(names)
    return f'"""{doc}"""\n\nfrom {new_module_path} import {imports}\n\n__all__ = [{names_str}]\n'


def move_file(src: Path, dst: Path, import_map: dict[str, str] | None = None,
              shim_module: str | None = None, shim_names: list[str] | None = None) -> None:
    """Move real code from src to dst, create shim at src."""
    if not src.exists():
        print(f"  SKIP {src.relative_to(APP.parent)} (not found)")
        return

    content = src.read_text()

    # Check if src is already a shim
    if "Compatibility shim" in content[:200] and "import *" in content[:300]:
        print(f"  SKIP {src.relative_to(APP.parent)} (already a shim)")
        return

    # Update imports in the content being moved
    updated = update_imports(content, import_map)

    # Ensure destination directory exists
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Write real code to new location
    dst.write_text(updated)

    # Create shim at old location
    if shim_module:
        if shim_names:
            shim = make_shim_with_all(shim_module, shim_names)
        else:
            shim = make_shim(shim_module)
        src.write_text(shim)
        print(f"  MOVE {src.relative_to(APP.parent)} → {dst.relative_to(APP.parent)}")
    else:
        print(f"  COPY {src.relative_to(APP.parent)} → {dst.relative_to(APP.parent)} (no shim)")


def move_module(old_pkg: str, new_pkg: str, import_map: dict[str, str] | None = None,
                file_renames: dict[str, str] | None = None) -> None:
    """Move all .py files from old package to new package, create shims."""
    old_dir = APP / old_pkg.replace(".", "/")
    new_dir = APP / new_pkg.replace(".", "/")

    if not old_dir.exists():
        print(f"  SKIP {old_pkg} (directory not found)")
        return

    # Build the import replacement map for this module
    module_map = {
        f"from app.{old_pkg}.": f"from app.{new_pkg}.",
        f"from app.{old_pkg} ": f"from app.{new_pkg} ",
        f"import app.{old_pkg}.": f"import app.{new_pkg}.",
        f"import app.{old_pkg}\n": f"import app.{new_pkg}\n",
    }
    if import_map:
        module_map.update(import_map)

    new_dir.mkdir(parents=True, exist_ok=True)

    # Ensure __init__.py exists in new dir
    init = new_dir / "__init__.py"
    if not init.exists():
        init.write_text("")

    for py_file in sorted(old_dir.rglob("*.py")):
        if "__pycache__" in str(py_file):
            continue

        rel = py_file.relative_to(old_dir)
        content = py_file.read_text()

        # Skip if already a shim
        if "Compatibility shim" in content[:200] and "import *" in content[:300]:
            print(f"  SKIP {py_file.relative_to(APP.parent)} (already a shim)")
            continue

        # Determine destination filename (handle renames)
        dst_name = str(rel)
        if file_renames and dst_name in file_renames:
            dst_name = file_renames[dst_name]

        dst = new_dir / dst_name
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Compute module path for shim
        old_module = f"app.{old_pkg}"
        new_module = f"app.{new_pkg}"
        if rel != Path("__init__.py"):
            # For non-init files, add the module name
            mod_parts = list(rel.with_suffix("").parts)
            old_module += "." + ".".join(mod_parts)
            # Use destination name for new module path
            dst_parts = list(Path(dst_name).with_suffix("").parts)
            new_module += "." + ".".join(dst_parts)

        if str(rel) == "__init__.py":
            # For __init__.py, check if new dir already has one with content
            if dst.exists():
                existing = dst.read_text()
                if existing.strip() and "Compatibility shim" not in existing[:200]:
                    # New __init__.py has real content (e.g., re-exports), keep it
                    # But still make old __init__.py a shim if it has real logic
                    if len(content.strip()) > 50:  # more than just empty or docstring
                        py_file.write_text(make_shim(f"app.{new_pkg}"))
                        print(f"  SHIM {py_file.relative_to(APP.parent)} → app.{new_pkg}")
                    continue

            # Update imports and write
            updated = update_imports(content, import_map)
            dst.write_text(updated)
            if len(content.strip()) > 50:
                py_file.write_text(make_shim(f"app.{new_pkg}"))
                print(f"  MOVE {py_file.relative_to(APP.parent)} → {dst.relative_to(APP.parent)}")
            continue

        # Check if destination is currently a forward-pointing shim
        if dst.exists():
            dst_content = dst.read_text()
            if f"from app.{old_pkg}" in dst_content and "import *" in dst_content:
                # It's a forward shim — overwrite with real code
                pass
            elif "Compatibility shim" not in dst_content[:200]:
                # Destination has real code already — skip
                print(f"  SKIP {dst.relative_to(APP.parent)} (already has real code)")
                continue

        # Update imports in moved content
        updated = update_imports(content, import_map)

        # Write to new location
        dst.write_text(updated)

        # Create shim at old location
        py_file.write_text(make_shim(new_module))
        print(f"  MOVE {py_file.relative_to(APP.parent)} → {dst.relative_to(APP.parent)}")


def wave_1():
    """Fix phase 2 gaps + observability + worker."""
    print("\n=== WAVE 1: Phase 2 gaps + Observability + Worker ===\n")

    # 1a. public_urls.py — core already has real code, just make old one a shim
    old = APP / "public_urls.py"
    if old.exists():
        content = old.read_text()
        if "Compatibility shim" not in content[:200]:
            old.write_text(make_shim("app.core.public_urls"))
            print("  SHIM app/public_urls.py → app.core.public_urls")

    # 1b. edition.py → core/edition.py
    move_file(
        APP / "edition.py",
        APP / "core" / "edition.py",
        shim_module="app.core.edition",
    )

    # 1c. persistent_config.py → core/persistent_config.py
    move_file(
        APP / "persistent_config.py",
        APP / "core" / "persistent_config.py",
        import_map={
            "from app.cache import": "from app.cache import",  # not moved yet
            "from app.cache.provider import": "from app.cache.provider import",  # not moved yet
        },
        shim_module="app.core.persistent_config",
    )

    # 2a. health/ → observability/health/
    obs_health = APP / "observability" / "health"
    obs_health.mkdir(parents=True, exist_ok=True)

    for fname in ["service.py", "schemas.py"]:
        src = APP / "health" / fname
        dst = obs_health / fname
        if src.exists():
            content = src.read_text()
            if "Compatibility shim" not in content[:200]:
                updated = update_imports(content)
                dst.write_text(updated)
                mod_name = fname.replace(".py", "")
                src.write_text(make_shim(f"app.observability.health.{mod_name}"))
                print(f"  MOVE app/health/{fname} → app/observability/health/{fname}")

    # 2b. worker_health.py → observability/health/worker.py
    move_file(
        APP / "worker_health.py",
        obs_health / "worker.py",
        shim_module="app.observability.health.worker",
    )

    # 2c. metrics/ → observability/metrics/
    obs_metrics = APP / "observability" / "metrics"
    obs_metrics.mkdir(parents=True, exist_ok=True)

    for fname in ["instrumentator.py", "jobs.py", "pool.py"]:
        src = APP / "metrics" / fname
        dst = obs_metrics / fname
        if src.exists():
            content = src.read_text()
            if "Compatibility shim" not in content[:200]:
                updated = update_imports(content)
                dst.write_text(updated)
                mod_name = fname.replace(".py", "")
                src.write_text(make_shim(f"app.observability.metrics.{mod_name}"))
                print(f"  MOVE app/metrics/{fname} → app/observability/metrics/{fname}")

    # Also handle metrics __init__.py if it has re-exports
    metrics_init = APP / "metrics" / "__init__.py"
    if metrics_init.exists():
        content = metrics_init.read_text().strip()
        if content and "Compatibility shim" not in content[:200]:
            obs_metrics_init = obs_metrics / "__init__.py"
            updated = update_imports(content)
            obs_metrics_init.write_text(updated)
            metrics_init.write_text(make_shim("app.observability.metrics"))
            print("  MOVE app/metrics/__init__.py → app/observability/metrics/__init__.py")

    # 2d. worker.py → platform/jobs/worker.py
    pjobs = APP / "platform" / "jobs"
    pjobs.mkdir(parents=True, exist_ok=True)

    src = APP / "worker.py"
    dst = pjobs / "worker.py"
    if src.exists():
        content = src.read_text()
        if "Compatibility shim" not in content[:200]:
            updated = update_imports(content)
            dst.write_text(updated)
            # Special shim — preserve __main__ block
            src.write_text(
                '"""Compatibility shim — real code moved to app.platform.jobs.worker."""\n\n'
                'from app.platform.jobs.worker import *  # noqa: F403\n\n'
                'if __name__ == "__main__":\n'
                '    import asyncio\n'
                '    asyncio.run(main())\n'
            )
            print("  MOVE app/worker.py → app/platform/jobs/worker.py")


def wave_2():
    """Move unmapped modules (no pre-existing shim dirs)."""
    print("\n=== WAVE 2: Unmapped modules ===\n")

    # middleware/ → api/middleware/
    move_module("middleware", "api.middleware")

    # config_ops/ → platform/config_ops/
    move_module("config_ops", "platform.config_ops")

    # sandbox/ → platform/sandbox/
    move_module("sandbox", "platform.sandbox")

    # extensions/ → platform/extensions/
    move_module("extensions", "platform.extensions")

    # assets/ → platform/assets/
    move_module("assets", "platform.assets")

    # models/base.py — delete if only contains Base that's already in core/db
    models_base = APP / "models" / "base.py"
    if models_base.exists():
        content = models_base.read_text()
        if "class Base" in content or "from app" in content:
            models_base.write_text(make_shim_with_all("app.core.db", ["Base"]))
            print("  SHIM app/models/base.py → app.core.db.Base")

    # Update api/router.py and api/main.py to use new paths for moved modules
    for target in ["api/router.py", "api/main.py"]:
        fpath = APP / target
        if fpath.exists():
            content = fpath.read_text()
            updated = content
            updated = updated.replace(
                "from app.config_ops.router import",
                "from app.platform.config_ops.router import",
            )
            updated = updated.replace(
                "from app.extensions import",
                "from app.platform.extensions import",
            )
            updated = updated.replace(
                "from app.middleware.", "from app.api.middleware."
            )
            if updated != content:
                fpath.write_text(updated)
                print(f"  UPDATE app/{target} (canonical import paths)")


def wave_3():
    """Move domain modules (audit phases 4-6)."""
    print("\n=== WAVE 3: Domain modules ===\n")

    # Batch 3a — Leaf modules
    move_module("audit", "modules.audit")
    move_module("settings", "modules.settings")
    move_module("validation", "modules.catalog.validation")

    # Batch 3b — Auth
    move_module("auth", "modules.auth")

    # Batch 3c — Catalog domain
    move_module("admin", "modules.admin")
    move_module("collections", "modules.catalog.collections")
    move_module("features", "modules.catalog.features")
    move_module("layers", "modules.catalog.layers")
    move_module("maps", "modules.catalog.maps")
    move_module("records", "modules.catalog.records")
    move_module("search", "modules.catalog.search")
    move_module("embed_tokens", "modules.embed_tokens")

    # services → sources (rename)
    move_module("services", "modules.catalog.sources", file_renames={
        "arcgis.py": "adapters/arcgis.py",
        "wfs.py": "adapters/wfs.py",
    })

    # datasets (split into api/ + domain/)
    ds_dir = APP / "datasets"
    if ds_dir.exists():
        api_files = [
            "router.py", "router_data.py", "router_export.py",
            "router_metadata.py", "router_reupload.py", "router_vrt.py",
        ]
        domain_files = [
            "models.py", "schemas.py", "service.py", "helpers.py",
            "utils.py", "column_stats.py",
        ]
        new_base = APP / "modules" / "catalog" / "datasets"
        new_api = new_base / "api"
        new_domain = new_base / "domain"
        new_api.mkdir(parents=True, exist_ok=True)
        new_domain.mkdir(parents=True, exist_ok=True)

        # Ensure __init__.py files
        for d in [new_base, new_api, new_domain]:
            init = d / "__init__.py"
            if not init.exists():
                init.write_text("")

        for fname in api_files:
            src = ds_dir / fname
            dst = new_api / fname
            if src.exists():
                content = src.read_text()
                if "Compatibility shim" in content[:200]:
                    continue
                updated = update_imports(content)
                # Also update intra-datasets imports
                updated = updated.replace(
                    "from app.datasets.service ", "from app.modules.catalog.datasets.domain.service "
                )
                updated = updated.replace(
                    "from app.datasets.service import", "from app.modules.catalog.datasets.domain.service import"
                )
                updated = updated.replace(
                    "from app.datasets.schemas ", "from app.modules.catalog.datasets.domain.schemas "
                )
                updated = updated.replace(
                    "from app.datasets.schemas import", "from app.modules.catalog.datasets.domain.schemas import"
                )
                updated = updated.replace(
                    "from app.datasets.models ", "from app.modules.catalog.datasets.domain.models "
                )
                updated = updated.replace(
                    "from app.datasets.models import", "from app.modules.catalog.datasets.domain.models import"
                )
                updated = updated.replace(
                    "from app.datasets.helpers ", "from app.modules.catalog.datasets.domain.helpers "
                )
                updated = updated.replace(
                    "from app.datasets.helpers import", "from app.modules.catalog.datasets.domain.helpers import"
                )
                updated = updated.replace(
                    "from app.datasets.utils ", "from app.modules.catalog.datasets.domain.utils "
                )
                updated = updated.replace(
                    "from app.datasets.utils import", "from app.modules.catalog.datasets.domain.utils import"
                )
                updated = updated.replace(
                    "from app.datasets.column_stats ", "from app.modules.catalog.datasets.domain.column_stats "
                )
                updated = updated.replace(
                    "from app.datasets.column_stats import", "from app.modules.catalog.datasets.domain.column_stats import"
                )
                dst.write_text(updated)
                mod = fname.replace(".py", "")
                src.write_text(make_shim(f"app.modules.catalog.datasets.api.{mod}"))
                print(f"  MOVE app/datasets/{fname} → app/modules/catalog/datasets/api/{fname}")

        for fname in domain_files:
            src = ds_dir / fname
            dst = new_domain / fname
            if src.exists():
                content = src.read_text()
                if "Compatibility shim" in content[:200]:
                    continue
                updated = update_imports(content)
                # Update intra-datasets refs
                updated = updated.replace(
                    "from app.datasets.", "from app.modules.catalog.datasets.domain."
                )
                dst.write_text(updated)
                mod = fname.replace(".py", "")
                src.write_text(make_shim(f"app.modules.catalog.datasets.domain.{mod}"))
                print(f"  MOVE app/datasets/{fname} → app/modules/catalog/datasets/domain/{fname}")


def wave_4():
    """Move processing modules (audit phase 7)."""
    print("\n=== WAVE 4: Processing modules ===\n")

    move_module("ai", "processing.ai")
    move_module("embeddings", "processing.embeddings")
    move_module("export", "processing.export")
    move_module("raster", "processing.raster")
    move_module("tiles", "processing.tiles")
    move_module("vector", "processing.vector")

    # ingest — needs special handling for Procrastinate import_paths
    move_module("ingest", "processing.ingest")

    # Update import_paths in the moved tasks.py
    tasks_file = APP / "processing" / "ingest" / "tasks.py"
    if tasks_file.exists():
        content = tasks_file.read_text()
        content = content.replace(
            'import_paths=["app.ingest.tasks", "app.embeddings.tasks", "app.raster.cog"]',
            'import_paths=["app.processing.ingest.tasks", "app.processing.embeddings.tasks"]',
        )
        tasks_file.write_text(content)
        print("  UPDATE import_paths in processing/ingest/tasks.py")

    # Add aliases to Procrastinate task decorators
    _add_task_aliases()


def _add_task_aliases():
    """Add backward-compat aliases to all Procrastinate task decorators."""
    # ingest tasks
    tasks_file = APP / "processing" / "ingest" / "tasks.py"
    if not tasks_file.exists():
        return
    content = tasks_file.read_text()

    ingest_tasks = [
        "ingest_file", "ingest_service", "reupload_file",
        "reupload_service", "ingest_raster", "ingest_vrt", "regenerate_vrt",
    ]
    for task_name in ingest_tasks:
        old_name = f"app.ingest.tasks.{task_name}"
        # Find @task_app.task(...) before the function def
        # Pattern: @task_app.task(queue="...", ...) or @task_app.task(...)
        # We need to add aliases=["old_name"] to the decorator
        pattern = rf'(@task_app\.task\([^)]*)\)\s*\n(async def {task_name}\b)'
        match = re.search(pattern, content)
        if match:
            decorator_args = match.group(1)
            func_def = match.group(2)
            if "aliases=" not in decorator_args:
                new_decorator = f'{decorator_args}, aliases=["{old_name}"])\n{func_def}'
                content = content[:match.start()] + new_decorator + content[match.end():]
                print(f"  ALIAS {task_name} → {old_name}")

    tasks_file.write_text(content)

    # embed_record task
    embed_file = APP / "processing" / "embeddings" / "tasks.py"
    if embed_file.exists():
        content = embed_file.read_text()
        old_name = "app.embeddings.tasks.embed_record"
        pattern = r'(@task_app\.task\([^)]*)\)\s*\n(async def embed_record\b)'
        match = re.search(pattern, content)
        if match:
            decorator_args = match.group(1)
            func_def = match.group(2)
            if "aliases=" not in decorator_args:
                new_decorator = f'{decorator_args}, aliases=["{old_name}"])\n{func_def}'
                content = content[:match.start()] + new_decorator + content[match.end():]
                print(f"  ALIAS embed_record → {old_name}")
                embed_file.write_text(content)


def wave_5():
    """Move standards (audit phase 8)."""
    print("\n=== WAVE 5: Standards ===\n")
    move_module("ogc", "standards.ogc")
    move_module("stac", "standards.stac")
    move_module("dcat", "standards.dcat")


def wave_6():
    """Move platform infrastructure."""
    print("\n=== WAVE 6: Platform infrastructure ===\n")
    move_module("cache", "platform.cache")
    move_module("storage", "platform.storage")
    move_module("jobs", "platform.jobs")


def wave_7():
    """Import standardization across all files."""
    print("\n=== WAVE 7: Import standardization ===\n")

    # Build comprehensive import map for all moved modules
    module_moves = {
        "app.admin.": "app.modules.admin.",
        "app.audit.": "app.modules.audit.",
        "app.auth.": "app.modules.auth.",
        "app.collections.": "app.modules.catalog.collections.",
        "app.embed_tokens.": "app.modules.embed_tokens.",
        "app.features.": "app.modules.catalog.features.",
        "app.layers.": "app.modules.catalog.layers.",
        "app.maps.": "app.modules.catalog.maps.",
        "app.records.": "app.modules.catalog.records.",
        "app.search.": "app.modules.catalog.search.",
        "app.services.": "app.modules.catalog.sources.",
        "app.settings.": "app.modules.settings.",
        "app.validation.": "app.modules.catalog.validation.",
        "app.ai.": "app.processing.ai.",
        "app.embeddings.": "app.processing.embeddings.",
        "app.export.": "app.processing.export.",
        "app.ingest.": "app.processing.ingest.",
        "app.raster.": "app.processing.raster.",
        "app.tiles.": "app.processing.tiles.",
        "app.vector.": "app.processing.vector.",
        "app.ogc.": "app.standards.ogc.",
        "app.stac.": "app.standards.stac.",
        "app.dcat.": "app.standards.dcat.",
        "app.cache.": "app.platform.cache.",
        "app.cache import": "app.platform.cache import",
        "app.storage.": "app.platform.storage.",
        "app.storage import": "app.platform.storage import",
        "app.jobs.": "app.platform.jobs.",
        "app.health.": "app.observability.health.",
        "app.metrics.": "app.observability.metrics.",
        "app.middleware.": "app.api.middleware.",
        "app.config_ops.": "app.platform.config_ops.",
        "app.sandbox.": "app.platform.sandbox.",
        "app.sandbox import": "app.platform.sandbox import",
        "app.extensions.": "app.platform.extensions.",
        "app.extensions import": "app.platform.extensions import",
        "app.assets.": "app.platform.assets.",
        "app.worker_health.": "app.observability.health.worker.",
    }

    # Also handle datasets split
    ds_domain = [
        "models", "schemas", "service", "helpers", "utils", "column_stats",
    ]
    ds_api = [
        "router", "router_data", "router_export", "router_metadata",
        "router_reupload", "router_vrt",
    ]
    for mod in ds_domain:
        module_moves[f"app.datasets.{mod}"] = f"app.modules.catalog.datasets.domain.{mod}"
    for mod in ds_api:
        module_moves[f"app.datasets.{mod}"] = f"app.modules.catalog.datasets.api.{mod}"

    count = 0
    # Walk ALL .py files under app/ that are NOT shims
    for py_file in sorted(APP.rglob("*.py")):
        if "__pycache__" in str(py_file):
            continue

        content = py_file.read_text()

        # Skip shims
        if "Compatibility shim" in content[:200] and "import *" in content[:300]:
            continue

        # Apply all replacements
        updated = content
        for old, new in module_moves.items():
            # Only replace in import statements
            for prefix in ["from ", "import "]:
                old_import = prefix + old
                new_import = prefix + new
                if old_import in updated:
                    updated = updated.replace(old_import, new_import)

        if updated != content:
            py_file.write_text(updated)
            count += 1
            print(f"  UPDATE {py_file.relative_to(APP.parent)}")

    print(f"\n  Updated imports in {count} files")


def verify():
    """Verify that key imports still work."""
    print("\n=== VERIFICATION ===\n")
    import subprocess
    checks = [
        "from app.api.main import app",
        "from app.core.config import settings",
        "from app.core.db import Base, async_session, engine",
        "from app.core.dependencies import get_db",
        "from app.config import settings",  # backward compat
        "from app.database import Base",  # backward compat
        "from app.dependencies import get_db",  # backward compat
        "from app.main import app",  # backward compat
    ]
    for check in checks:
        result = subprocess.run(
            [sys.executable, "-c", check],
            capture_output=True, text=True,
        )
        status = "OK" if result.returncode == 0 else "FAIL"
        print(f"  {status}: {check}")
        if result.returncode != 0:
            print(f"       {result.stderr.strip().split(chr(10))[-1]}")


def main():
    parser = argparse.ArgumentParser(description="Backend restructuring migration tool")
    parser.add_argument("--wave", type=int, help="Run a specific wave (1-7)")
    parser.add_argument("--verify", action="store_true", help="Verify imports work")
    args = parser.parse_args()

    if args.verify:
        verify()
    elif args.wave == 1:
        wave_1()
        verify()
    elif args.wave == 2:
        wave_2()
        verify()
    elif args.wave == 3:
        wave_3()
        verify()
    elif args.wave == 4:
        wave_4()
        verify()
    elif args.wave == 5:
        wave_5()
        verify()
    elif args.wave == 6:
        wave_6()
        verify()
    elif args.wave == 7:
        wave_7()
        verify()
    else:
        print("Usage: python scripts/refactor_migrate.py --wave N  (N=1..7)")
        print("       python scripts/refactor_migrate.py --verify")


if __name__ == "__main__":
    main()

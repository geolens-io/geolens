"""Quicklook PNG thumbnail generation for raster assets."""

import io


def _crop_to_valid(data, nodata):
    """Return (row_start, row_end, col_start, col_end) bounding the valid pixels.

    Works for both 2-D (H, W) and 3-D (C, H, W) arrays.
    Returns None if there are no valid pixels.
    """
    import numpy as np

    if data.ndim == 3:
        # Valid if any band is not nodata.
        if nodata is not None:
            valid_mask = np.any(data != nodata, axis=0)
        else:
            valid_mask = np.ones(data.shape[1:], dtype=bool)
    else:
        if nodata is not None:
            valid_mask = data != nodata
        else:
            valid_mask = np.ones(data.shape, dtype=bool)

    rows = np.any(valid_mask, axis=1)
    cols = np.any(valid_mask, axis=0)
    if not rows.any():
        return None
    r_start, r_end = np.where(rows)[0][[0, -1]]
    c_start, c_end = np.where(cols)[0][[0, -1]]
    return int(r_start), int(r_end) + 1, int(c_start), int(c_end) + 1


def generate_quicklook(cog_path: str, size: int) -> bytes:
    """Generate a square PNG thumbnail from a COG file.

    Uses the lowest overview level that meets `size`. Multi-band (>=3) uses
    bands 1-3 as RGB; single-band uses a 2nd/98th percentile stretch.
    Crops to valid-data extent first, so nodata doesn't dominate the
    thumbnail; aspect ratio preserved with letterboxing.
    """
    import numpy as np
    import rasterio
    from PIL import Image

    with rasterio.open(cog_path) as src:
        # An overview with at least `size` pixels on the long edge, else full
        # resolution.
        overviews = src.overviews(1)
        out_w, out_h = src.width, src.height
        if overviews:
            for dec_factor in reversed(overviews):
                cand_w = max(1, src.width // dec_factor)
                cand_h = max(1, src.height // dec_factor)
                if max(cand_w, cand_h) >= size:
                    out_w, out_h = cand_w, cand_h
                    break

        # The selection above bounds nothing alone: the smallest available
        # level is read whatever its size, so a sparse overview ladder could
        # make `out_shape` demand ~30GB from a 500MB-capped upload.
        #
        # 2x is free from a complete ladder (the chosen level is always under
        # twice `size`) and only matters when the ladder stops short. It is not
        # `size` itself because `_crop_to_valid` crops before resizing, and
        # cropping at `size` upscales a nodata-heavy result.
        max_edge = size * 2
        if max(out_w, out_h) > max_edge:
            scale = max_edge / max(out_w, out_h)
            out_w = max(1, round(out_w * scale))
            out_h = max(1, round(out_h * scale))

        nodata = src.nodata

        if src.count >= 3:
            data = src.read(
                [1, 2, 3],
                out_shape=(3, out_h, out_w),
                resampling=rasterio.enums.Resampling.nearest,
            )

            bounds = _crop_to_valid(data, nodata)
            if bounds is not None:
                r0, r1, c0, c1 = bounds
                data = data[:, r0:r1, c0:c1]

            is_byte = np.issubdtype(data.dtype, np.uint8)
            if is_byte:
                arr = np.moveaxis(data, 0, -1)
            else:
                # Non-uint8 (e.g. uint16): per-band percentile stretch
                _, ch, cw = data.shape
                stretched = np.empty((3, ch, cw), dtype=np.uint8)
                for i in range(3):
                    band = data[i].astype(np.float64)
                    if nodata is not None:
                        valid = band[band != nodata]
                    else:
                        valid = band.ravel()
                    if valid.size == 0:
                        stretched[i] = 0
                        continue
                    p2 = float(np.percentile(valid, 2))
                    p98 = float(np.percentile(valid, 98))
                    if p98 == p2:
                        stretched[i] = 0
                    else:
                        stretched[i] = np.clip(
                            (band - p2) / (p98 - p2) * 255, 0, 255
                        ).astype(np.uint8)
                arr = np.moveaxis(stretched, 0, -1)

            img = Image.fromarray(arr, mode="RGB")
        else:
            # Single band: stretched to 0-255 grayscale.
            band = src.read(
                1,
                out_shape=(out_h, out_w),
                resampling=rasterio.enums.Resampling.nearest,
            ).astype(np.float64)

            if nodata is not None:
                mask = band == nodata
            else:
                mask = np.zeros_like(band, dtype=bool)

            bounds = _crop_to_valid(band, nodata)
            if bounds is not None:
                r0, r1, c0, c1 = bounds
                band = band[r0:r1, c0:c1]
                mask = mask[r0:r1, c0:c1]

            valid = band[~mask]

            from PIL import ImageOps

            if valid.size == 0 or np.all(mask):
                # All nodata: mid-gray so the thumbnail is visible, not black.
                img_gray = Image.fromarray(
                    np.full((out_h, out_w), 128, dtype=np.uint8), mode="L"
                )
            else:
                p2 = float(np.percentile(valid, 2))
                p98 = float(np.percentile(valid, 98))

                if p98 == p2:
                    # Zero range: a flat mid-gray image rather than black.
                    stretched = np.full_like(band, 128, dtype=np.uint8)
                else:
                    stretched = np.clip((band - p2) / (p98 - p2) * 255, 0, 255)
                    stretched = stretched.astype(np.uint8)
                    stretched[mask] = 0

                img_gray = Image.fromarray(stretched, mode="L")

            img = ImageOps.colorize(
                img_gray, black="#1e3a5f", white="#f1f5f9", mid="#60a5fa"
            )

    if img.mode == "L":
        img = img.convert("RGB")

    # Aspect ratio preserved by letterboxing onto a light canvas.
    img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (241, 245, 249))  # slate-50
    offset_x = (size - img.width) // 2
    offset_y = (size - img.height) // 2
    canvas.paste(img, (offset_x, offset_y))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=False)
    return buf.getvalue()

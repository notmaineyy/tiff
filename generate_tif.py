"""
Generate a TIFF file and its corresponding GDAL .aux.xml sidecar.

The TIFF contains synthetic raster data; the .aux.xml stores georeferencing
(GeoTransform + SRS) and per-band statistics in GDAL's PAM format.

Usage:
    python generate_tif.py [output_basename] [--width W] [--height H]
"""

import argparse
import math
import random
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image


def make_raster(width: int, height: int):
    """Create synthetic RGB data (a smooth gradient with noise)."""
    random.seed(42)
    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 3
            pixels[i] = int(255 * x / max(width - 1, 1))          # red: horizontal gradient
            pixels[i + 1] = int(255 * y / max(height - 1, 1))     # green: vertical gradient
            pixels[i + 2] = random.randint(0, 255)                # blue: noise
    return bytes(pixels)


def write_tiff(path: Path, width: int, height: int) -> None:
    img = Image.frombytes("RGB", (width, height), make_raster(width, height))
    # LZW keeps it small; use "tiff_deflate" if you prefer ZIP compression
    img.save(path, format="TIFF", compression="tiff_lzw")


def write_aux_xml(
    tif_path: Path,
    geo_transform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    stats_per_band: list[dict],
) -> Path:
    """Write a GDAL PAM .aux.xml next to the TIFF."""
    aux_path = tif_path.with_suffix(tif_path.suffix + ".aux.xml")

    pam = ET.Element("PAMDataset")
    ET.SubElement(pam, "SRS").text = srs_wkt
    ET.SubElement(pam, "GeoTransform").text = ", ".join(str(v) for v in geo_transform)

    meta = ET.SubElement(pam, "Metadata", {"domain": "IMAGE_STRUCTURE"})
    ET.SubElement(meta, "MDI", {"key": "INTERLEAVE"}).text = "PIXEL"

    for i, st in enumerate(stats_per_band, start=1):
        band = ET.SubElement(pam, "PAMRasterBand", {"band": str(i)})
        ET.SubElement(
            band,
            "Statistics",
            {
                "MINIMUM": f"{st['min']:.6f}",
                "MAXIMUM": f"{st['max']:.6f}",
                "MEAN": f"{st['mean']:.6f}",
                "STDDEV": f"{st['stddev']:.6f}",
            },
        )

    ET.indent(pam, space="  ")
    ET.ElementTree(pam).write(aux_path, encoding="UTF-8", xml_declaration=True)
    return aux_path


def compute_band_stats(img: Image.Image) -> list[dict]:
    """Per-band min/max/mean/stddev statistics."""
    bands = img.split()
    stats = []
    for band in bands:
        hist = band.histogram()
        total = sum(hist)
        minimum = next(i for i, c in enumerate(hist) if c)
        maximum = len(hist) - 1 - next(i for i, c in enumerate(reversed(hist)) if c)
        mean = sum(i * c for i, c in enumerate(hist)) / total
        variance = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total
        stats.append(
            {"min": minimum, "max": maximum, "mean": mean, "stddev": math.sqrt(variance)}
        )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("basename", nargs="?", default="output", help="output basename (no ext)")
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    args = parser.parse_args()

    out_dir = Path(__file__).parent
    tif_path = out_dir / f"{args.basename}.tif"

    write_tiff(tif_path, args.width, args.height)

    # Georeferencing: map pixels to a simple location (Web Mercator-ish).
    origin_x, origin_y = -10500000.0, 4500000.0
    pixel_size = 10.0
    geo_transform = (origin_x, pixel_size, 0.0, origin_y, 0.0, -pixel_size)

    wgs84_utm13n = (
        'PROJCS["WGS 84 / UTM zone 13N",GEOGCS["WGS 84",'
        'DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
        'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
        'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
        'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
        'AUTHORITY["EPSG","4326"]],'
        'PROJECTION["Transverse_Mercator"],'
        'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-105],'
        'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
        'PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
        'AXIS["Easting",EAST],AXIS["Northing",NORTH],AUTHORITY["EPSG","32613"]]'
    )

    img = Image.open(tif_path)
    aux_path = write_aux_xml(tif_path, geo_transform, wgs84_utm13n, compute_band_stats(img))

    print(f"Created: {tif_path}")
    print(f"Created: {aux_path}")


if __name__ == "__main__":
    main()

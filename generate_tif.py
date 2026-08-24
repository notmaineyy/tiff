"""
Generate a TIFF file and its corresponding GDAL .aux.xml sidecar.

The TIFF contains synthetic raster data; the .aux.xml stores georeferencing
(GeoTransform + SRS) and per-band statistics in GDAL's PAM format.

Usage:
    python generate_tif.py [output_basename] [--width W] [--height H] [--count N]
"""

import argparse
import math
import random
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image


def make_raster(width: int, height: int, seed: int = 42):
    """Create synthetic 8-bit grayscale data (a smooth gradient with noise)."""
    rng = random.Random(seed)
    pixels = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            i = y * width + x
            gradient = (int(255 * x / max(width - 1, 1)) + int(255 * y / max(height - 1, 1))) // 2
            pixels[i] = min(gradient + rng.randint(-16, 16), 255) & 0xFF
    return bytes(pixels)


def write_tiff(path: Path, width: int, height: int, seed: int = 42) -> None:
    img = Image.frombytes("L", (width, height), make_raster(width, height, seed))
    # Uncompressed, 8 bits per channel, 5 DPI in both directions
    img.save(path, format="TIFF", compression=None, dpi=(5, 5))


def write_aux_xml(
    tif_path: Path,
    aux_dir: Path,
    geo_transform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    stats_per_band: list[dict],
) -> Path:
    """Write a GDAL PAM .aux.xml next to the TIFF."""
    aux_path = aux_dir / f"{tif_path.stem}.aux.xml"

    pam = _build_pam_dataset(geo_transform, srs_wkt, stats_per_band)

    ET.indent(pam, space="  ")
    ET.ElementTree(pam).write(aux_path, encoding="UTF-8", xml_declaration=True)
    return aux_path


def write_aux(
    tif_path: Path,
    aux_dir: Path,
    geo_transform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    stats_per_band: list[dict],
) -> Path:
    """Write the same PAM metadata as a plain-text .aux sidecar."""
    aux_path = aux_dir / f"{tif_path.stem}.aux"

    pam = _build_pam_dataset(geo_transform, srs_wkt, stats_per_band)

    ET.indent(pam, space="  ")
    ET.ElementTree(pam).write(aux_path, encoding="UTF-8", xml_declaration=True)
    return aux_path


def _build_pam_dataset(
    geo_transform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    stats_per_band: list[dict],
) -> ET.Element:
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
    return pam


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
    parser.add_argument("--count", type=int, default=1000, help="number of unique TIFFs to generate")
    args = parser.parse_args()

    out_dir = Path(__file__).parent
    tif_dir = out_dir / "tif"
    aux_dir = out_dir / "auxfiles"  # "aux" is a reserved device name on Windows
    tif_dir.mkdir(exist_ok=True)
    aux_dir.mkdir(exist_ok=True)

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

    for i in range(1, args.count + 1):
        tif_path = tif_dir / f"{args.basename}_{i:04d}.tif"

        write_tiff(tif_path, args.width, args.height, seed=i)

        img = Image.open(tif_path)
        stats = compute_band_stats(img)
        write_aux_xml(tif_path, aux_dir, geo_transform, wgs84_utm13n, stats)
        write_aux(tif_path, aux_dir, geo_transform, wgs84_utm13n, stats)

    print(f"Generated {args.count} unique TIFF file(s) in {tif_dir} with sidecars in {aux_dir}")


if __name__ == "__main__":
    main()

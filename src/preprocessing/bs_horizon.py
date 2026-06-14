"""Port of ``src/fortran/bs_horizon.f`` for DEM interpolation.

This module keeps the original BS-Horizon formulation and input concepts:

- elevation constraints: ``id x y z lm``
- strike/dip constraints: ``id x y z trend dip``
- sentinel row: any record whose X coordinate absolute value exceeds ``1e9``

The implementation exposes a CLI that replaces the original interactive
Fortran workflow with explicit arguments while preserving the same numerical
steps, output formats, and constraint handling.
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SENTINEL_LIMIT = 1.0e9
SPLIT_PATTERN = re.compile(r"[\s,]+")


@dataclass(frozen=True)
class DataExtents:
    """Bounding information collected from the input observations."""

    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float


@dataclass(frozen=True)
class ElevationData:
    """Elevation observations and their equality or inequality relations."""

    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    relation: np.ndarray
    extents: DataExtents


@dataclass(frozen=True)
class DipData:
    """Strike/dip observations converted to target partial derivatives."""

    x: np.ndarray
    y: np.ndarray
    trend_deg: np.ndarray
    dip_deg: np.ndarray
    dfdx: np.ndarray
    dfdy: np.ndarray


@dataclass(frozen=True)
class SurfaceRegion:
    """Calculation region and B-spline division counts."""

    xmin: float
    xmax: float
    ymin: float
    ymax: float
    mx: int
    my: int


@dataclass(frozen=True)
class SolveParameters:
    """Penalty and smoothness parameters for BS-Horizon."""

    alpha_min: float
    alpha_max: float
    iterations: int
    gamma: float
    m1: float
    m2: float


@dataclass(frozen=True)
class IterationSummary:
    """Per-iteration diagnostics reported by the original program."""

    iteration: int
    alpha: float
    gamma: float
    nh_constraints: int
    nd_constraints: int
    rh: float
    rh_error: float
    rd: float
    rd_error: float
    jx: float
    jy: float
    jxx: float
    jxy: float
    jyy: float
    j1: float
    j2: float
    q: float
    j: float
    ar: float


@dataclass(frozen=True)
class BsHorizonResult:
    """Solved cubic B-spline surface and derived metadata."""

    region: SurfaceRegion
    parameters: SolveParameters
    hx: float
    hy: float
    neq: int
    coefficients: np.ndarray
    summaries: tuple[IterationSummary, ...]

    def evaluate_surface(self, x_coord: float, y_coord: float) -> float:
        """Evaluate the solved surface at one coordinate."""
        return _evaluate_surface_value(
            x_coord=x_coord,
            y_coord=y_coord,
            xmin=self.region.xmin,
            xmax=self.region.xmax,
            ymin=self.region.ymin,
            ymax=self.region.ymax,
            mx=self.region.mx,
            my=self.region.my,
            hx=self.hx,
            hy=self.hy,
            coeffs=self.coefficients,
        )


def _iter_records(file_path: Path, expected_columns: int) -> Iterable[list[str]]:
    """Yield parsed numeric tokens from a whitespace or CSV-like text file."""
    with file_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = [token for token in SPLIT_PATTERN.split(line) if token]
            if len(fields) < expected_columns:
                raise ValueError(
                    f"Invalid record in {file_path}: expected at least "
                    f"{expected_columns} columns, got {len(fields)}"
                )
            yield fields


def read_elevation_data(file_path: Path) -> ElevationData:
    """Read ``id x y z [lm]`` records until the sentinel row appears.

    lm 列は省略可能。省略時は全点を等式制約（lm=0）として扱う。
    """
    resolved = file_path if file_path.is_absolute() else (PROJECT_ROOT / file_path)
    resolved = resolved.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Elevation file not found: {resolved}")

    x_values: list[float] = []
    y_values: list[float] = []
    z_values: list[float] = []
    relation_values: list[int] = []

    xmin = xmax = ymin = ymax = zmin = zmax = None
    for fields in _iter_records(resolved, expected_columns=4):
        x_coord = float(fields[1])
        if abs(x_coord) > SENTINEL_LIMIT:
            break

        y_coord = float(fields[2])
        z_coord = float(fields[3])
        relation = int(round(float(fields[4]))) if len(fields) >= 5 else 0

        x_values.append(x_coord)
        y_values.append(y_coord)
        z_values.append(z_coord)
        relation_values.append(relation)

        if xmin is None:
            xmin = xmax = x_coord
            ymin = ymax = y_coord
            zmin = zmax = z_coord
            continue

        xmin = min(xmin, x_coord)
        xmax = max(xmax, x_coord)
        ymin = min(ymin, y_coord)
        ymax = max(ymax, y_coord)
        zmin = min(zmin, z_coord)
        zmax = max(zmax, z_coord)

    if not x_values:
        raise ValueError(f"No elevation data found in {resolved}")

    extents = DataExtents(
        xmin=float(xmin),
        xmax=float(xmax),
        ymin=float(ymin),
        ymax=float(ymax),
        zmin=float(zmin),
        zmax=float(zmax),
    )
    return ElevationData(
        x=np.asarray(x_values, dtype=np.float64),
        y=np.asarray(y_values, dtype=np.float64),
        z=np.asarray(z_values, dtype=np.float64),
        relation=np.asarray(relation_values, dtype=np.int64),
        extents=extents,
    )


def read_dip_data(
    file_path: Path | None, elevation_extents: DataExtents
) -> tuple[DipData, DataExtents]:
    """Read optional strike/dip records and expand the data extents."""
    if file_path is None:
        empty = np.asarray([], dtype=np.float64)
        dip_data = DipData(
            x=empty,
            y=empty,
            trend_deg=empty,
            dip_deg=empty,
            dfdx=empty,
            dfdy=empty,
        )
        return dip_data, elevation_extents

    resolved = file_path if file_path.is_absolute() else (PROJECT_ROOT / file_path)
    resolved = resolved.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Strike/dip file not found: {resolved}")

    x_values: list[float] = []
    y_values: list[float] = []
    trend_values: list[float] = []
    dip_values: list[float] = []
    dfdx_values: list[float] = []
    dfdy_values: list[float] = []

    xmin = elevation_extents.xmin
    xmax = elevation_extents.xmax
    ymin = elevation_extents.ymin
    ymax = elevation_extents.ymax
    radians_per_degree = math.pi / 180.0

    for fields in _iter_records(resolved, expected_columns=6):
        x_coord = float(fields[1])
        if abs(x_coord) > SENTINEL_LIMIT:
            break

        y_coord = float(fields[2])
        trend = float(fields[4])
        dip = float(fields[5])

        x_values.append(x_coord)
        y_values.append(y_coord)
        trend_values.append(trend)
        dip_values.append(dip)
        dfdx_values.append(
            -math.sin(radians_per_degree * trend) * math.tan(radians_per_degree * dip)
        )
        dfdy_values.append(
            -math.cos(radians_per_degree * trend) * math.tan(radians_per_degree * dip)
        )

        xmin = min(xmin, x_coord)
        xmax = max(xmax, x_coord)
        ymin = min(ymin, y_coord)
        ymax = max(ymax, y_coord)

    if not x_values:
        raise ValueError(f"No strike/dip data found in {resolved}")

    dip_data = DipData(
        x=np.asarray(x_values, dtype=np.float64),
        y=np.asarray(y_values, dtype=np.float64),
        trend_deg=np.asarray(trend_values, dtype=np.float64),
        dip_deg=np.asarray(dip_values, dtype=np.float64),
        dfdx=np.asarray(dfdx_values, dtype=np.float64),
        dfdy=np.asarray(dfdy_values, dtype=np.float64),
    )
    extents = DataExtents(
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        zmin=elevation_extents.zmin,
        zmax=elevation_extents.zmax,
    )
    return dip_data, extents


def _basis_values(r_value: float, interval: float, derivative_order: int) -> np.ndarray:
    """Return non-zero cubic B-spline basis values using 1-based slots."""
    basis = np.zeros(5, dtype=np.float64)
    if derivative_order == 0:
        coeff = 1.0 / 6.0
        basis[1] = (r_value**3) * coeff
        basis[2] = (3.0 * (-(r_value**3) + r_value**2 + r_value) + 1.0) * coeff
        basis[3] = (3.0 * r_value**3 - 6.0 * r_value**2 + 4.0) * coeff
        basis[4] = (-(r_value**3) + 3.0 * (r_value**2 - r_value) + 1.0) * coeff
    elif derivative_order == 1:
        coeff = 0.5 / interval
        basis[1] = (r_value**2) * coeff
        basis[2] = (-3.0 * r_value**2 + 2.0 * r_value + 1.0) * coeff
        basis[3] = (3.0 * r_value**2 - 4.0 * r_value) * coeff
        basis[4] = (-(r_value**2) + 2.0 * r_value - 1.0) * coeff
    elif derivative_order == 2:
        coeff = 1.0 / (interval**2)
        basis[1] = r_value * coeff
        basis[2] = (-3.0 * r_value + 1.0) * coeff
        basis[3] = (3.0 * r_value - 2.0) * coeff
        basis[4] = (-r_value + 1.0) * coeff
    else:
        raise ValueError(f"Unsupported derivative order: {derivative_order}")
    return basis


def _integral_values(divisions: int, derivative_order: int, knot_index: int) -> np.ndarray:
    """Return 1-based integration values for the four local B-spline functions."""
    values = np.zeros(5, dtype=np.float64)
    if derivative_order == 0:
        if knot_index == 1:
            values[1], values[2], values[3], values[4] = (
                1.0 / 252.0,
                43.0 / 1680.0,
                1.0 / 84.0,
                1.0 / 5040.0,
            )
        elif knot_index == 2:
            values[1], values[2], values[3], values[4] = (
                151.0 / 630.0,
                59.0 / 280.0,
                1.0 / 42.0,
                1.0 / 5040.0,
            )
        elif knot_index == 3:
            values[1], values[2], values[3], values[4] = (
                599.0 / 1260.0,
                397.0 / 1680.0,
                1.0 / 42.0,
                1.0 / 5040.0,
            )
        elif knot_index == divisions + 1:
            values[1], values[2], values[3], values[4] = (
                599.0 / 1260.0,
                59.0 / 280.0,
                1.0 / 84.0,
                0.0,
            )
        elif knot_index == divisions + 2:
            values[1], values[2], values[3], values[4] = (
                151.0 / 630.0,
                43.0 / 1680.0,
                0.0,
                0.0,
            )
        elif knot_index == divisions + 3:
            values[1], values[2], values[3], values[4] = (1.0 / 252.0, 0.0, 0.0, 0.0)
        else:
            values[1], values[2], values[3], values[4] = (
                151.0 / 315.0,
                397.0 / 1680.0,
                1.0 / 42.0,
                1.0 / 5040.0,
            )
    elif derivative_order == 1:
        if knot_index == 1:
            values[1], values[2], values[3], values[4] = (
                1.0 / 20.0,
                7.0 / 120.0,
                -1.0 / 10.0,
                -1.0 / 120.0,
            )
        elif knot_index == 2:
            values[1], values[2], values[3], values[4] = (
                1.0 / 3.0,
                -11.0 / 60.0,
                -1.0 / 5.0,
                -1.0 / 120.0,
            )
        elif knot_index == 3:
            values[1], values[2], values[3], values[4] = (
                37.0 / 60.0,
                -1.0 / 8.0,
                -1.0 / 5.0,
                -1.0 / 120.0,
            )
        elif knot_index == divisions + 1:
            values[1], values[2], values[3], values[4] = (
                37.0 / 60.0,
                -11.0 / 60.0,
                -1.0 / 10.0,
                0.0,
            )
        elif knot_index == divisions + 2:
            values[1], values[2], values[3], values[4] = (
                1.0 / 3.0,
                7.0 / 120.0,
                0.0,
                0.0,
            )
        elif knot_index == divisions + 3:
            values[1], values[2], values[3], values[4] = (1.0 / 20.0, 0.0, 0.0, 0.0)
        else:
            values[1], values[2], values[3], values[4] = (
                2.0 / 3.0,
                -1.0 / 8.0,
                -1.0 / 5.0,
                -1.0 / 120.0,
            )
    elif derivative_order == 2:
        if knot_index == 1:
            values[1], values[2], values[3], values[4] = (1.0 / 3.0, -1.0 / 2.0, 0.0, 1.0 / 6.0)
        elif knot_index == 2:
            values[1], values[2], values[3], values[4] = (4.0 / 3.0, -1.0, 0.0, 1.0 / 6.0)
        elif knot_index == 3:
            values[1], values[2], values[3], values[4] = (7.0 / 3.0, -3.0 / 2.0, 0.0, 1.0 / 6.0)
        elif knot_index == divisions + 1:
            values[1], values[2], values[3], values[4] = (7.0 / 3.0, -1.0, 0.0, 0.0)
        elif knot_index == divisions + 2:
            values[1], values[2], values[3], values[4] = (4.0 / 3.0, -1.0 / 2.0, 0.0, 0.0)
        elif knot_index == divisions + 3:
            values[1], values[2], values[3], values[4] = (1.0 / 3.0, 0.0, 0.0, 0.0)
        else:
            values[1], values[2], values[3], values[4] = (8.0 / 3.0, -3.0 / 2.0, 0.0, 1.0 / 6.0)
    else:
        raise ValueError(f"Unsupported derivative order: {derivative_order}")
    return values


def _point_in_region(
    x_coord: float,
    y_coord: float,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
) -> bool:
    """Return whether a point belongs to the closed calculation region."""
    return xmin <= x_coord <= xmax and ymin <= y_coord <= ymax


def _knot_indices_and_offsets(
    x_coord: float,
    y_coord: float,
    xmin: float,
    ymin: float,
    hx: float,
    hy: float,
    mx: int,
    my: int,
) -> tuple[int, int, float, float]:
    """Return right-hand knot indices and normalized local coordinates."""
    ipx = int((x_coord - xmin) / hx) + 1
    ipy = int((y_coord - ymin) / hy) + 1
    if ipx == mx + 1:
        ipx = mx
    if ipy == my + 1:
        ipy = my
    rx = (x_coord - xmin) / hx - float(ipx - 1)
    ry = (y_coord - ymin) / hy - float(ipy - 1)
    return ipx, ipy, rx, ry


def _evaluate_surface_value(
    x_coord: float,
    y_coord: float,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    mx: int,
    my: int,
    hx: float,
    hy: float,
    coeffs: np.ndarray,
) -> float:
    """Evaluate the cubic B-spline surface at one point inside the region."""
    if not _point_in_region(x_coord, y_coord, xmin, xmax, ymin, ymax):
        raise ValueError("Point is outside the calculation region.")

    ipx, ipy, rx, ry = _knot_indices_and_offsets(x_coord, y_coord, xmin, ymin, hx, hy, mx, my)
    bx0 = _basis_values(rx, hx, 0)
    by0 = _basis_values(ry, hy, 0)
    value = 0.0
    stride = mx + 3
    for j_offset in range(0, 4):
        for i_offset in range(0, 4):
            index = ipx + i_offset + (ipy - 1 + j_offset) * stride
            value += coeffs[index] * bx0[4 - i_offset] * by0[4 - j_offset]
    return value


def _set_b_ah(
    elevation: ElevationData,
    region: SurfaceRegion,
    alpha: float,
    coeffs: np.ndarray,
    b_vec: np.ndarray,
    a_mat: np.ndarray,
    hx: float,
    hy: float,
) -> int:
    """Set the banded matrix and RHS terms from elevation constraints."""
    nhdt = 0
    for x_coord, y_coord in zip(elevation.x, elevation.y, strict=True):
        if _point_in_region(x_coord, y_coord, region.xmin, region.xmax, region.ymin, region.ymax):
            nhdt += 1

    if nhdt == 0:
        raise ValueError("No elevation data fall inside the calculation region.")

    weight = alpha / float(nhdt)
    stride = region.mx + 3
    for x_coord, y_coord, z_coord, relation in zip(
        elevation.x,
        elevation.y,
        elevation.z,
        elevation.relation,
        strict=True,
    ):
        if not _point_in_region(
            x_coord, y_coord, region.xmin, region.xmax, region.ymin, region.ymax
        ):
            continue

        ipx, ipy, rx, ry = _knot_indices_and_offsets(
            x_coord=x_coord,
            y_coord=y_coord,
            xmin=region.xmin,
            ymin=region.ymin,
            hx=hx,
            hy=hy,
            mx=region.mx,
            my=region.my,
        )
        bx0 = _basis_values(rx, hx, 0)
        by0 = _basis_values(ry, hy, 0)

        estimate = 0.0
        for j_offset in range(0, 4):
            for i_offset in range(0, 4):
                index = ipx + i_offset + (ipy - 1 + j_offset) * stride
                estimate += coeffs[index] * bx0[4 - i_offset] * by0[4 - j_offset]

        residual = estimate - z_coord
        if relation != 0 and residual * float(relation) > 0.0:
            continue

        for j1 in range(0, 4):
            for i1 in range(0, 4):
                row = ipx + i1 + (ipy - 1 + j1) * stride
                w1 = bx0[4 - i1] * by0[4 - j1]
                b_vec[row] += weight * w1 * z_coord
                for j2 in range(0, 4):
                    for i2 in range(0, 4):
                        column = (i2 - i1) + 1 + (j2 - j1) * stride
                        if column <= 0:
                            continue
                        w2 = bx0[4 - i2] * by0[4 - j2]
                        a_mat[row, column] += weight * w1 * w2

    return nhdt


def _set_b_ad(
    dip_data: DipData,
    region: SurfaceRegion,
    alpha: float,
    gamma: float,
    b_vec: np.ndarray,
    a_mat: np.ndarray,
    hx: float,
    hy: float,
) -> int:
    """Set the banded matrix and RHS terms from slope constraints."""
    if dip_data.x.size == 0:
        return 0

    nddt = 0
    for x_coord, y_coord in zip(dip_data.x, dip_data.y, strict=True):
        if _point_in_region(x_coord, y_coord, region.xmin, region.xmax, region.ymin, region.ymax):
            nddt += 1

    if nddt == 0:
        raise ValueError("No strike/dip data fall inside the calculation region.")

    beta = alpha * gamma
    weight = beta / float(nddt)
    stride = region.mx + 3
    for x_coord, y_coord, dfdx_value, dfdy_value in zip(
        dip_data.x,
        dip_data.y,
        dip_data.dfdx,
        dip_data.dfdy,
        strict=True,
    ):
        if not _point_in_region(
            x_coord, y_coord, region.xmin, region.xmax, region.ymin, region.ymax
        ):
            continue

        ipx, ipy, rx, ry = _knot_indices_and_offsets(
            x_coord=x_coord,
            y_coord=y_coord,
            xmin=region.xmin,
            ymin=region.ymin,
            hx=hx,
            hy=hy,
            mx=region.mx,
            my=region.my,
        )
        bx0 = _basis_values(rx, hx, 0)
        bx1 = _basis_values(rx, hx, 1)
        by0 = _basis_values(ry, hy, 0)
        by1 = _basis_values(ry, hy, 1)

        for j1 in range(0, 4):
            for i1 in range(0, 4):
                row = ipx + i1 + (ipy - 1 + j1) * stride
                b_vec[row] += weight * bx1[4 - i1] * by0[4 - j1] * dfdx_value
                b_vec[row] += weight * bx0[4 - i1] * by1[4 - j1] * dfdy_value
                for j2 in range(0, 4):
                    for i2 in range(0, 4):
                        column = (i2 - i1) + 1 + (j2 - j1) * stride
                        if column <= 0:
                            continue
                        a_mat[row, column] += (
                            weight * bx1[4 - i1] * by0[4 - j1] * bx1[4 - i2] * by0[4 - j2]
                        )
                        a_mat[row, column] += (
                            weight * bx0[4 - i1] * by1[4 - j1] * bx0[4 - i2] * by1[4 - j2]
                        )

    return nddt


def _set_j(
    a_mat: np.ndarray,
    region: SurfaceRegion,
    parameters: SolveParameters,
    hx: float,
    hy: float,
) -> None:
    """Set the smoothness penalty terms into the banded matrix."""
    wx = parameters.m1 * (hy / hx) / float(region.mx * region.my)
    wy = parameters.m1 * (hx / hy) / float(region.mx * region.my)
    wxx = parameters.m2 * hy / (hx**3)
    wxy = 2.0 * parameters.m2 / (hx * hy)
    wyy = parameters.m2 * hx / (hy**3)

    for j1 in range(1, region.my + 4):
        ffiy0 = _integral_values(region.my, 0, j1)
        ffiy1 = _integral_values(region.my, 1, j1)
        ffiy2 = _integral_values(region.my, 2, j1)
        j22 = 4 if j1 < region.my + 1 else region.my + 4 - j1

        for i1 in range(1, region.mx + 4):
            ffix0 = _integral_values(region.mx, 0, i1)
            ffix1 = _integral_values(region.mx, 1, i1)
            ffix2 = _integral_values(region.mx, 2, i1)
            row = i1 + (j1 - 1) * (region.mx + 3)
            i22 = 4 if i1 < region.mx + 1 else region.mx + 4 - i1

            _set_j_tmp(a_mat, region.mx, wx, row, i22, j22, ffix1, ffiy0)
            _set_j_tmp(a_mat, region.mx, wy, row, i22, j22, ffix0, ffiy1)
            _set_j_tmp(a_mat, region.mx, wxx, row, i22, j22, ffix2, ffiy0)
            _set_j_tmp(a_mat, region.mx, wxy, row, i22, j22, ffix1, ffiy1)
            _set_j_tmp(a_mat, region.mx, wyy, row, i22, j22, ffix0, ffiy2)


def _set_j_tmp(
    a_mat: np.ndarray,
    mx: int,
    weight: float,
    row: int,
    i22: int,
    j22: int,
    ffix: np.ndarray,
    ffiy: np.ndarray,
) -> None:
    """Translate Fortran ``setJtmp`` exactly, including copied band entries."""
    stride = mx + 3
    for j2 in range(1, j22 + 1):
        for i2 in range(1, i22 + 1):
            column = i2 + (j2 - 1) * stride
            value = weight * ffix[i2] * ffiy[j2]
            a_mat[row, column] += value
            if j2 >= 2 and i2 >= 2:
                copied_row = row + i2 - 1
                copied_column = column - 2 * (i2 - 1)
                a_mat[copied_row, copied_column] += value


def _choles_solve(a_mat: np.ndarray, b_vec: np.ndarray, neq: int, nbs: int) -> np.ndarray:
    """Solve the banded normal equation with the translated Cholesky routine."""
    a_work = a_mat.copy()
    b_work = b_vec.copy()
    coeffs = np.zeros_like(b_vec)

    a_work[1, 1] = math.sqrt(a_work[1, 1])
    b_work[1] = b_work[1] / a_work[1, 1]
    for jt in range(2, nbs + 1):
        a_work[1, jt] = a_work[1, jt] / a_work[1, 1]

    for row in range(2, neq + 1):
        row_minus_1 = row - 1
        row_start = 1 if row < nbs else row - nbs + 1

        diagonal_sum = 0.0
        for source_row in range(row_start, row_minus_1 + 1):
            offset = row - source_row + 1
            diagonal_sum += a_work[source_row, offset] ** 2
        a_work[row, 1] = math.sqrt(a_work[row, 1] - diagonal_sum)

        if neq - row >= nbs:
            max_band = nbs
        else:
            max_band = neq - row + 1

        if max_band > 1:
            for jt in range(2, max_band + 1):
                if row >= nbs:
                    start_row = row_start + jt - 1
                elif jt > nbs - row:
                    start_row = jt - (nbs - row)
                else:
                    start_row = 1

                off_diagonal_sum = 0.0
                if start_row <= row_minus_1:
                    for source_row in range(start_row, row_minus_1 + 1):
                        offset = row - source_row + 1
                        shifted_offset = offset + jt - 1
                        off_diagonal_sum += (
                            a_work[source_row, offset] * a_work[source_row, shifted_offset]
                        )
                a_work[row, jt] = (a_work[row, jt] - off_diagonal_sum) / a_work[row, 1]

        rhs_sum = 0.0
        for source_row in range(row_start, row_minus_1 + 1):
            offset = row - source_row + 1
            rhs_sum += a_work[source_row, offset] * b_work[source_row]
        b_work[row] = (b_work[row] - rhs_sum) / a_work[row, 1]

    coeffs[neq] = b_work[neq] / a_work[neq, 1]
    for reverse_offset in range(1, neq):
        row = neq - reverse_offset
        max_terms = reverse_offset + 1 if reverse_offset < nbs else nbs
        solution_sum = 0.0
        for band in range(2, max_terms + 1):
            coeff_index = row + band - 1
            solution_sum += a_work[row, band] * coeffs[coeff_index]
        coeffs[row] = (b_work[row] - solution_sum) / a_work[row, 1]

    return coeffs


def _reconstruct_dense_matrix(a_mat: np.ndarray, neq: int, nbs: int) -> np.ndarray:
    """Reconstruct the full symmetric matrix from the Fortran band layout."""
    dense = np.zeros((neq, neq), dtype=np.float64)
    for row_index in range(1, neq + 1):
        max_offset = min(nbs - 1, neq - row_index)
        for offset in range(0, max_offset + 1):
            column_index = row_index + offset
            value = a_mat[row_index, offset + 1]
            dense[row_index - 1, column_index - 1] = value
            dense[column_index - 1, row_index - 1] = value
    return dense


def _solve_banded_system(a_mat: np.ndarray, b_vec: np.ndarray, neq: int, nbs: int) -> np.ndarray:
    """Solve the symmetric banded system, preferring SciPy's tested solver."""
    try:
        from scipy.linalg import solveh_banded
    except ImportError:
        return _choles_solve(a_mat, b_vec, neq, nbs)

    upper_bandwidth = nbs - 1
    ab = np.zeros((upper_bandwidth + 1, neq), dtype=np.float64)
    for row_index in range(1, neq + 1):
        max_offset = min(upper_bandwidth, neq - row_index)
        for offset in range(0, max_offset + 1):
            column_index = row_index + offset
            ab[upper_bandwidth - offset, column_index - 1] = a_mat[row_index, offset + 1]

    rhs = b_vec[1 : neq + 1]
    try:
        solution = solveh_banded(ab, rhs, lower=False, check_finite=False)
    except Exception:
        if neq > 2000:
            return _choles_solve(a_mat, b_vec, neq, nbs)
        dense = _reconstruct_dense_matrix(a_mat, neq, nbs)
        solution = np.linalg.solve(dense, rhs)

    coeffs = np.zeros(neq + 1, dtype=np.float64)
    coeffs[1 : neq + 1] = solution
    return coeffs


def _rh_value(
    elevation: ElevationData,
    region: SurfaceRegion,
    hx: float,
    hy: float,
    coeffs: np.ndarray,
) -> tuple[int, float, float]:
    """Evaluate the residual mean square for elevation constraints."""
    nhdt = 0
    residual_sum = 0.0
    stride = region.mx + 3

    for x_coord, y_coord, z_coord, relation in zip(
        elevation.x,
        elevation.y,
        elevation.z,
        elevation.relation,
        strict=True,
    ):
        if not _point_in_region(
            x_coord, y_coord, region.xmin, region.xmax, region.ymin, region.ymax
        ):
            continue

        ipx, ipy, rx, ry = _knot_indices_and_offsets(
            x_coord=x_coord,
            y_coord=y_coord,
            xmin=region.xmin,
            ymin=region.ymin,
            hx=hx,
            hy=hy,
            mx=region.mx,
            my=region.my,
        )
        bx0 = _basis_values(rx, hx, 0)
        by0 = _basis_values(ry, hy, 0)
        estimate = 0.0
        for j_offset in range(0, 4):
            for i_offset in range(0, 4):
                index = ipx + i_offset + (ipy - 1 + j_offset) * stride
                estimate += coeffs[index] * bx0[4 - i_offset] * by0[4 - j_offset]
        residual = estimate - z_coord
        if relation != 0 and residual * float(relation) > 0.0:
            continue

        residual_sum += residual**2
        nhdt += 1

    qrh = residual_sum / float(nhdt)
    return nhdt, qrh, math.sqrt(qrh)


def _rd_value(
    dip_data: DipData,
    region: SurfaceRegion,
    hx: float,
    hy: float,
    nddt: int,
    coeffs: np.ndarray,
) -> tuple[float, float]:
    """Evaluate the residual mean square for strike/dip constraints."""
    if dip_data.x.size == 0:
        return 0.0, 0.0

    rdx = 0.0
    rdy = 0.0
    stride = region.mx + 3
    for x_coord, y_coord, dfdx_value, dfdy_value in zip(
        dip_data.x,
        dip_data.y,
        dip_data.dfdx,
        dip_data.dfdy,
        strict=True,
    ):
        if not _point_in_region(
            x_coord, y_coord, region.xmin, region.xmax, region.ymin, region.ymax
        ):
            continue

        ipx, ipy, rx, ry = _knot_indices_and_offsets(
            x_coord=x_coord,
            y_coord=y_coord,
            xmin=region.xmin,
            ymin=region.ymin,
            hx=hx,
            hy=hy,
            mx=region.mx,
            my=region.my,
        )
        bx0 = _basis_values(rx, hx, 0)
        bx1 = _basis_values(rx, hx, 1)
        by0 = _basis_values(ry, hy, 0)
        by1 = _basis_values(ry, hy, 1)
        fdx = 0.0
        fdy = 0.0
        for j_offset in range(0, 4):
            for i_offset in range(0, 4):
                index = ipx + i_offset + (ipy - 1 + j_offset) * stride
                fdx += coeffs[index] * bx1[4 - i_offset] * by0[4 - j_offset]
                fdy += coeffs[index] * bx0[4 - i_offset] * by1[4 - j_offset]
        rdx += (fdx - dfdx_value) ** 2
        rdy += (fdy - dfdy_value) ** 2

    qrd = (rdx + rdy) / float(nddt)
    return qrd, math.sqrt(qrd)


def _j_value(
    region: SurfaceRegion,
    parameters: SolveParameters,
    hx: float,
    hy: float,
    coeffs: np.ndarray,
) -> tuple[float, float, float, float, float, float, float, float]:
    """Evaluate the smoothness terms of the final solution."""
    wx = hy / hx / float(region.mx * region.my)
    wy = hx / hy / float(region.mx * region.my)
    wxx = hy / (hx**3)
    wxy = 1.0 / (hx * hy)
    wyy = hx / (hy**3)

    qjx = qjy = qjxx = qjxy = qjyy = 0.0
    for j1 in range(1, region.my + 4):
        ffiy0 = _integral_values(region.my, 0, j1)
        ffiy1 = _integral_values(region.my, 1, j1)
        ffiy2 = _integral_values(region.my, 2, j1)
        j22 = 4 if j1 < region.my + 1 else region.my + 4 - j1

        for i1 in range(1, region.mx + 4):
            ffix0 = _integral_values(region.mx, 0, i1)
            ffix1 = _integral_values(region.mx, 1, i1)
            ffix2 = _integral_values(region.mx, 2, i1)
            i22 = 4 if i1 < region.mx + 1 else region.mx + 4 - i1

            qjx += _j_tmp(coeffs, region.mx, wx, i1, j1, i22, j22, ffix1, ffiy0)
            qjy += _j_tmp(coeffs, region.mx, wy, i1, j1, i22, j22, ffix0, ffiy1)
            qjxx += _j_tmp(coeffs, region.mx, wxx, i1, j1, i22, j22, ffix2, ffiy0)
            qjxy += _j_tmp(coeffs, region.mx, wxy, i1, j1, i22, j22, ffix1, ffiy1)
            qjyy += _j_tmp(coeffs, region.mx, wyy, i1, j1, i22, j22, ffix0, ffiy2)

    qj1 = qjx + qjy
    qj2 = qjxx + 2.0 * qjxy + qjyy
    qj = parameters.m1 * qj1 + parameters.m2 * qj2
    return qjx, qjy, qjxx, qjxy, qjyy, qj1, qj2, qj


def _j_tmp(
    coeffs: np.ndarray,
    mx: int,
    weight: float,
    i1: int,
    j1: int,
    i22: int,
    j22: int,
    ffix: np.ndarray,
    ffiy: np.ndarray,
) -> float:
    """Translate Fortran ``Jtmp`` exactly, including the second cross term."""
    total = 0.0
    stride = mx + 3
    for j2 in range(1, j22 + 1):
        for i2 in range(1, i22 + 1):
            value = weight * ffix[i2] * ffiy[j2]
            index_a = i1 + (j1 - 1) * stride
            index_b = (i1 + i2 - 1) + ((j1 + j2 - 1) - 1) * stride
            if index_a == index_b:
                total += coeffs[index_a] * value * coeffs[index_b]
            else:
                total += coeffs[index_a] * value * coeffs[index_b] * 2.0
                if j2 != 1 and i2 != 1:
                    index_c = (i1 + i2 - 1) + (j1 - 1) * stride
                    index_d = i1 + ((j1 + j2 - 1) - 1) * stride
                    total += coeffs[index_c] * value * coeffs[index_d] * 2.0
    return total


def solve_bs_horizon(
    elevation: ElevationData,
    dip_data: DipData,
    region: SurfaceRegion,
    parameters: SolveParameters,
) -> BsHorizonResult:
    """Solve the BS-Horizon constrained interpolation problem."""
    if parameters.alpha_min <= 0.0:
        raise ValueError("alpha_min must be positive.")
    if parameters.alpha_max < parameters.alpha_min:
        raise ValueError("alpha_max must be greater than or equal to alpha_min.")
    if parameters.iterations < 1:
        raise ValueError("iterations must be at least 1.")
    if parameters.gamma < 0.0:
        raise ValueError("gamma must be non-negative.")
    if parameters.m1 < 0.0 or parameters.m2 < 0.0:
        raise ValueError("m1 and m2 must be non-negative.")
    if region.xmax <= region.xmin or region.ymax <= region.ymin:
        raise ValueError("Invalid calculation region bounds.")
    if region.mx <= 0 or region.my <= 0:
        raise ValueError("mx and my must be positive.")

    inequality_count = int(np.count_nonzero(elevation.relation))
    if inequality_count == 0:
        if parameters.iterations != 1:
            raise ValueError(
                "Equality-only constraints must use exactly one iteration, "
                "as in the Fortran program."
            )
        if parameters.alpha_max != parameters.alpha_min:
            raise ValueError("Equality-only constraints must not vary alpha across iterations.")
    else:
        if parameters.iterations <= 1:
            raise ValueError(
                "Inequality constraints require more than one iteration, as in the Fortran program."
            )

    hx = (region.xmax - region.xmin) / float(region.mx)
    hy = (region.ymax - region.ymin) / float(region.my)
    neq = (region.mx + 3) * (region.my + 3)
    nbs = (region.mx + 3) * 3 + 4
    coeffs = np.zeros(neq + 1, dtype=np.float64)

    if parameters.iterations == 1:
        ratio = 1.0
    else:
        ratio = (parameters.alpha_max / parameters.alpha_min) ** (
            1.0 / float(parameters.iterations - 1)
        )

    summaries: list[IterationSummary] = []
    for iteration in range(1, parameters.iterations + 1):
        a_mat = np.zeros((neq + 1, nbs + 1), dtype=np.float64)
        b_vec = np.zeros(neq + 1, dtype=np.float64)
        alpha = parameters.alpha_min * (ratio ** float(iteration - 1))

        nhdt = _set_b_ah(elevation, region, alpha, coeffs, b_vec, a_mat, hx, hy)
        nddt = _set_b_ad(dip_data, region, alpha, parameters.gamma, b_vec, a_mat, hx, hy)
        _set_j(a_mat, region, parameters, hx, hy)
        coeffs = _solve_banded_system(a_mat, b_vec, neq, nbs)

        nh_value, qrh, qrh_error = _rh_value(elevation, region, hx, hy, coeffs)
        if nh_value != nhdt:
            raise RuntimeError(
                "Elevation constraint counting diverged from the translated algorithm."
            )

        qrd, qrd_error = _rd_value(dip_data, region, hx, hy, nddt, coeffs)
        qjx, qjy, qjxx, qjxy, qjyy, qj1, qj2, qj = _j_value(region, parameters, hx, hy, coeffs)
        qr = qrh + parameters.gamma * qrd
        ar = alpha * qr
        q_total = qj + ar

        summaries.append(
            IterationSummary(
                iteration=iteration,
                alpha=alpha,
                gamma=parameters.gamma,
                nh_constraints=nhdt,
                nd_constraints=nddt,
                rh=qrh,
                rh_error=qrh_error,
                rd=qrd,
                rd_error=qrd_error,
                jx=qjx,
                jy=qjy,
                jxx=qjxx,
                jxy=qjxy,
                jyy=qjyy,
                j1=qj1,
                j2=qj2,
                q=q_total,
                j=qj,
                ar=ar,
            )
        )

    return BsHorizonResult(
        region=region,
        parameters=parameters,
        hx=hx,
        hy=hy,
        neq=neq,
        coefficients=coeffs,
        summaries=tuple(summaries),
    )


def build_dem_grid(
    result: BsHorizonResult,
    xming: float,
    xmaxg: float,
    yming: float,
    ymaxg: float,
    nxg: int,
    nyg: int,
) -> tuple[np.ndarray, np.ndarray, float, float, np.ndarray]:
    """Generate the DEM grid using the same output convention as Fortran."""
    if xming < result.region.xmin or xmaxg > result.region.xmax:
        raise ValueError("DEM X bounds must stay inside the calculation region.")
    if yming < result.region.ymin or ymaxg > result.region.ymax:
        raise ValueError("DEM Y bounds must stay inside the calculation region.")
    if nxg < 2 or nyg < 2:
        raise ValueError("DEM grid counts must be at least 2.")

    dx = (xmaxg - xming) / float(nxg - 1)
    dy = (ymaxg - yming) / float(nyg - 1)
    x_coords = np.asarray([xming + float(index) * dx for index in range(nxg)], dtype=np.float64)
    y_coords = np.asarray([yming + float(index) * dy for index in range(nyg)], dtype=np.float64)
    dem = np.zeros((nxg, nyg), dtype=np.float64)

    for i, x_coord in enumerate(x_coords):
        for j, y_coord in enumerate(y_coords):
            dem[i, j] = result.evaluate_surface(float(x_coord), float(y_coord))

    return x_coords, y_coords, dx, dy, dem


def write_dem_file(
    file_path: Path,
    xming: float,
    yming: float,
    dx: float,
    dy: float,
    dem: np.ndarray,
) -> Path:
    """Write the DEM output in the same text layout as the Fortran program."""
    resolved = file_path if file_path.is_absolute() else (PROJECT_ROOT / file_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    nxg, nyg = dem.shape
    with resolved.open("w", encoding="utf-8") as handle:
        handle.write(f"{nxg} {nyg} {xming:.12g} {yming:.12g} {dx:.12g} {dy:.12g}\n")
        for i in range(nxg):
            row = " ".join(f"{value:.12g}" for value in dem[i, :])
            handle.write(f"{row}\n")
    return resolved.resolve()


def write_surface_file(file_path: Path, result: BsHorizonResult) -> Path:
    """Write spline coefficients in the original BS-Horizon text format."""
    resolved = file_path if file_path.is_absolute() else (PROJECT_ROOT / file_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    with resolved.open("w", encoding="utf-8") as handle:
        handle.write(
            f"{result.region.mx} {result.region.my} "
            f"{result.region.xmin:.12g} {result.region.ymin:.12g} "
            f"{result.hx:.12g} {result.hy:.12g}\n"
        )
        for index in range(1, result.neq + 1):
            handle.write(f"{result.coefficients[index]:16.9E}\n")
    return resolved.resolve()


def _load_yaml_config(config_path: Path) -> dict:
    """YAMLパラメータファイルを読み込んで辞書で返す。"""
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("YAMLサポートには PyYAML が必要です: pip install pyyaml") from exc
    resolved = config_path if config_path.is_absolute() else (PROJECT_ROOT / config_path)
    if not resolved.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。--config でYAMLファイルと組み合わせて使用できる。

    優先順位: CLIで明示した値 > YAMLの値。
    必須項目（elevation_file, mx, my, alpha_min, m1, m2）はどちらかで指定すれば足りる。
    """
    parser = argparse.ArgumentParser(
        description="BS-Horizon DEM補間をFortranからPython CLIに移植したもの。"
    )
    parser.add_argument("--config", type=Path, help="YAMLパラメータファイル（CLIと併用可）。")
    parser.add_argument("--elevation-file", type=Path, help="標高制約ファイル。")
    parser.add_argument("--dip-file", type=Path, help="走向傾斜制約ファイル（省略可）。")
    parser.add_argument("--xmin", type=float, help="計算領域のX最小値。")
    parser.add_argument("--xmax", type=float, help="計算領域のX最大値。")
    parser.add_argument("--ymin", type=float, help="計算領域のY最小値。")
    parser.add_argument("--ymax", type=float, help="計算領域のY最大値。")
    parser.add_argument("--mx", type=int, help="X方向の分割数。")
    parser.add_argument("--my", type=int, help="Y方向の分割数。")
    parser.add_argument("--alpha-min", type=float, help="ペナルティ初期値 alpha。")
    parser.add_argument("--alpha-max", type=float, help="ペナルティ最終値 alpha（反復あり時）。")
    parser.add_argument("--iterations", type=int, help="反復回数（デフォルト: 1）。")
    parser.add_argument("--gamma", type=float, help="走向傾斜データへの相対ペナルティ重み。")
    parser.add_argument("--m1", type=float, help="1次平滑化重み。")
    parser.add_argument("--m2", type=float, help="2次平滑化重み。")
    parser.add_argument(
        "--dem-output", type=Path, help="DEM グリッドテキスト出力ファイル（省略可）。"
    )
    parser.add_argument(
        "--surface-output", type=Path, help="スプライン係数出力ファイル（省略可）。"
    )
    parser.add_argument("--dem-xmin", type=float, help="DEM出力のX最小値。")
    parser.add_argument("--dem-xmax", type=float, help="DEM出力のX最大値。")
    parser.add_argument("--dem-ymin", type=float, help="DEM出力のY最小値。")
    parser.add_argument("--dem-ymax", type=float, help="DEM出力のY最大値。")
    parser.add_argument("--nxg", type=int, help="DEM グリッドのX点数。")
    parser.add_argument("--nyg", type=int, help="DEM グリッドのY点数。")
    args = parser.parse_args()

    # YAMLから設定を読み込み、CLIで未指定（None）の引数を補完する
    if args.config is not None:
        config = _load_yaml_config(args.config)
        _path_keys = {"elevation_file", "dip_file", "dem_output", "surface_output"}
        for key, value in config.items():
            if getattr(args, key, None) is None and value is not None:
                setattr(args, key, Path(value) if key in _path_keys else value)

    # iterations のデフォルト（YAMLもCLIも未指定の場合）
    if args.iterations is None:
        args.iterations = 1

    # 必須引数のバリデーション（CLIとYAMLを合わせて確認）
    _required = {
        "elevation_file": "--elevation-file",
        "mx": "--mx",
        "my": "--my",
        "alpha_min": "--alpha-min",
        "m1": "--m1",
        "m2": "--m2",
    }
    missing = [flag for attr, flag in _required.items() if getattr(args, attr, None) is None]
    if missing:
        parser.error(f"次の引数は必須です（--config または CLI で指定）: {', '.join(missing)}")

    return args


def main() -> None:
    """Run the translated BS-Horizon workflow from the command line."""
    args = parse_args()
    elevation = read_elevation_data(args.elevation_file)
    dip_data, combined_extents = read_dip_data(args.dip_file, elevation.extents)

    xmin = combined_extents.xmin if args.xmin is None else args.xmin
    xmax = combined_extents.xmax if args.xmax is None else args.xmax
    ymin = combined_extents.ymin if args.ymin is None else args.ymin
    ymax = combined_extents.ymax if args.ymax is None else args.ymax

    gamma = 0.0 if dip_data.x.size == 0 else (1.0 if args.gamma is None else args.gamma)
    alpha_max = args.alpha_min if args.alpha_max is None else args.alpha_max

    region = SurfaceRegion(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, mx=args.mx, my=args.my)
    parameters = SolveParameters(
        alpha_min=args.alpha_min,
        alpha_max=alpha_max,
        iterations=args.iterations,
        gamma=gamma,
        m1=args.m1,
        m2=args.m2,
    )
    result = solve_bs_horizon(elevation, dip_data, region, parameters)

    for summary in result.summaries:
        print("#####Estimation result#####")
        print(
            f"iteration={summary.iteration:4d}  alpha={summary.alpha:12.5E}  "
            f"gamma={summary.gamma:12.5E}"
        )
        print("------------------------------------------------------")
        print(
            f"H : data ={summary.nh_constraints:6d}  Rh ={summary.rh:12.5E}  "
            f"Error={summary.rh_error:12.5E}"
        )
        print(
            f"D : data ={summary.nd_constraints:6d}  Rd ={summary.rd:12.5E}  "
            f"Error={summary.rd_error:12.5E}"
        )
        print("------------------------------------------------------")
        print(f"Jx ={summary.jx:12.5E}  Jy ={summary.jy:12.5E}")
        print(f"Jxx={summary.jxx:12.5E}  Jxy={summary.jxy:12.5E}  Jyy={summary.jyy:12.5E}")
        print(f"J1 ={summary.j1:12.5E}  J2 ={summary.j2:12.5E}")
        print("------------------------------------------------------")
        print(f"Q  ={summary.q:12.5E}  J  ={summary.j:12.5E}  aR ={summary.ar:12.5E}")

    if args.dem_output is not None:
        if args.nxg is None or args.nyg is None:
            raise ValueError("DEM output requires both --nxg and --nyg.")
        dem_xmin = region.xmin if args.dem_xmin is None else args.dem_xmin
        dem_xmax = region.xmax if args.dem_xmax is None else args.dem_xmax
        dem_ymin = region.ymin if args.dem_ymin is None else args.dem_ymin
        dem_ymax = region.ymax if args.dem_ymax is None else args.dem_ymax
        _, _, dx, dy, dem = build_dem_grid(
            result=result,
            xming=dem_xmin,
            xmaxg=dem_xmax,
            yming=dem_ymin,
            ymaxg=dem_ymax,
            nxg=args.nxg,
            nyg=args.nyg,
        )
        dem_path = write_dem_file(args.dem_output, dem_xmin, dem_ymin, dx, dy, dem)
        print(f"DEM output: {dem_path}")

    if args.surface_output is not None:
        surface_path = write_surface_file(args.surface_output, result)
        print(f"Surface output: {surface_path}")


if __name__ == "__main__":
    main()

"""lst_emissivity_sensitivity.py（放射率の感度分析の差の集計）のテスト。

小さな合成ラスタ・合成の results.json で、照合・再現確認・差の統計・NDVI 階級別の集計・
分析ランの比較を手計算の値と突き合わせる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS

import src.analysis.lst_emissivity_sensitivity as sensitivity

TRANSFORM = Affine(0.5, 0.0, 100.0, 0.0, -0.5, 20.0)


def write_raster(
    path: Path,
    bands: list[np.ndarray],
    descriptions: list[str] | None = None,
    transform: Affine = TRANSFORM,
) -> Path:
    """float64 の GeoTIFF を書く。

    Args:
        path: 出力先。
        bands: バンドの値（同じ形状の 2 次元配列）。
        descriptions: バンド名。
        transform: アフィン変換。

    Returns:
        Path: 書いたファイルのパス。
    """
    height, width = bands[0].shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=len(bands),
        dtype="float64",
        crs=CRS.from_epsg(4326),
        transform=transform,
    ) as destination:
        for index, band in enumerate(bands, start=1):
            destination.write(band, index)
            if descriptions:
                destination.set_band_description(index, descriptions[index - 1])
    return path


# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------


def test_read_band_selects_band_by_description(tmp_path: Path) -> None:
    """バンド名で指標の NDVI バンドを選ぶ。"""
    path = write_raster(
        tmp_path / "indices.tif",
        [np.full((2, 2), 0.1), np.full((2, 2), 0.7)],
        descriptions=["NDBI", "NDVI"],
    )

    values, transform, crs_text = sensitivity.read_band(path, "NDVI")

    np.testing.assert_allclose(values, 0.7)
    assert transform == TRANSFORM
    assert crs_text == "EPSG:4326"


def test_read_band_rejects_missing_band(tmp_path: Path) -> None:
    """存在しないバンド名はエラーにする。"""
    path = write_raster(tmp_path / "indices.tif", [np.zeros((2, 2))], descriptions=["NDBI"])

    with pytest.raises(ValueError, match="NDVI"):
        sensitivity.read_band(path, "NDVI")


def test_load_aligned_bands_rejects_different_grid(tmp_path: Path) -> None:
    """グリッドがずれたラスタどうしは差を取らない。"""
    first = write_raster(tmp_path / "a.tif", [np.zeros((2, 2))])
    shifted = write_raster(
        tmp_path / "b.tif",
        [np.zeros((2, 2))],
        transform=Affine(0.5, 0.0, 100.5, 0.0, -0.5, 20.0),
    )

    with pytest.raises(ValueError, match="グリッド"):
        sensitivity.load_aligned_bands({"a": (first, None), "b": (shifted, None)})


def test_describe_values_includes_lower_percentiles() -> None:
    """負の差も扱えるよう下側の分位点を含め、手計算と一致する。"""
    summary = sensitivity.describe_values(np.array([-2.0, 0.0, 2.0, 4.0]))

    assert summary["count"] == 4
    assert summary["mean"] == pytest.approx(1.0)
    assert summary["min"] == pytest.approx(-2.0)
    assert summary["p50"] == pytest.approx(1.0)
    assert summary["p1"] == pytest.approx(np.percentile([-2.0, 0.0, 2.0, 4.0], 1))


def test_describe_values_handles_empty() -> None:
    """値が 0 件でも落ちず、統計を None にする。"""
    summary = sensitivity.describe_values(np.array([]))

    assert summary["count"] == 0
    assert summary["mean"] is None
    assert summary["p99"] is None


# ---------------------------------------------------------------------------
# method-check
# ---------------------------------------------------------------------------


def build_samples() -> pd.DataFrame:
    """3 点の照合用の表を作る（smw_ndvi は一致、em0 は 0.5 °C 高い、simple は 1 点欠測）。

    Returns:
        pd.DataFrame: 点の表。
    """
    return pd.DataFrame(
        {
            "point_id": [0, 1, 2],
            "row": [0, 1, 1],
            "col": [0, 0, 1],
            "x": [0.0, 0.0, 0.0],
            "y": [0.0, 0.0, 0.0],
            "lst_smw_ndvi": [30.0, 31.0, 32.0],
            "lst_smw_em0": [30.5, 31.5, 32.5],
            "lst_simple": [29.0, np.nan, 33.0],
        }
    )


def test_method_check_identifies_matching_method() -> None:
    """許容差以内で全点が一致した方式だけを一致とし、欠測は比べずに数える。"""
    reference = np.array([[30.0, np.nan], [31.0, 32.0000001]])

    table = sensitivity.attach_reference_values(build_samples(), reference)
    result = sensitivity.summarize_method_check(table, tolerance=1e-3)

    assert result["matching_methods"] == ["lst_smw_ndvi"]
    em0 = result["methods"]["lst_smw_em0"]
    assert em0["n_compared"] == 3
    assert em0["n_within_tolerance"] == 0
    assert em0["signed_difference_mean"] == pytest.approx(0.5, abs=1e-6)
    simple = result["methods"]["lst_simple"]
    assert simple["n_missing_method"] == 1
    assert simple["n_compared"] == 2


def test_method_check_does_not_match_when_nothing_compared() -> None:
    """比べられた点が無い方式は一致としない（全欠測を一致と誤判定しない）。"""
    samples = build_samples()
    samples["lst_simple"] = np.nan
    reference = np.array([[30.0, np.nan], [31.0, 32.0]])

    table = sensitivity.attach_reference_values(samples, reference)
    result = sensitivity.summarize_method_check(table, tolerance=1e-3)

    assert "lst_simple" not in result["matching_methods"]
    assert result["methods"]["lst_simple"]["signed_difference_mean"] is None


def test_attach_reference_values_rejects_out_of_range_points() -> None:
    """行・列が範囲外の点は別グリッドの点とみなしエラーにする。"""
    samples = build_samples()
    samples.loc[0, "row"] = 5

    with pytest.raises(ValueError, match="範囲外"):
        sensitivity.attach_reference_values(samples, np.zeros((2, 2)))


# ---------------------------------------------------------------------------
# lst-diff
# ---------------------------------------------------------------------------


def test_summarize_reproduction_detects_exact_match() -> None:
    """有効画素の位置が同じで差が許容差以内なら再現とみなす。"""
    reference = np.array([[30.0, np.nan], [31.0, 32.0]])

    result = sensitivity.summarize_reproduction(reference, reference + 1e-9, tolerance=1e-3)

    assert result["reproduced"] is True
    assert result["valid_both"] == 3
    assert result["n_exceeding_tolerance"] == 0


def test_summarize_reproduction_detects_mask_mismatch_and_value_difference() -> None:
    """有効画素の位置の違いと許容差を超える差を、それぞれ数える。"""
    reference = np.array([[30.0, np.nan], [31.0, 32.0]])
    reproduced = np.array([[30.0, 29.0], [np.nan, 32.5]])

    result = sensitivity.summarize_reproduction(reference, reproduced, tolerance=1e-3)

    assert result["reproduced"] is False
    assert result["valid_only_reference"] == 1
    assert result["valid_only_reproduced"] == 1
    assert result["n_exceeding_tolerance"] == 1
    assert result["abs_difference"]["max"] == pytest.approx(0.5)


def test_compute_difference_keeps_nan_where_either_invalid() -> None:
    """どちらかが無効な画素は NaN にし、0 として扱わない。"""
    difference = sensitivity.compute_difference(
        np.array([[2.0, np.nan], [3.0, 1.0]]), np.array([[1.0, 1.0], [np.nan, 1.5]])
    )

    np.testing.assert_array_equal(np.isnan(difference), [[False, True], [True, False]])
    assert difference[0, 0] == pytest.approx(1.0)
    assert difference[1, 1] == pytest.approx(-0.5)


def test_pearson_on_common_matches_numpy_and_handles_constant() -> None:
    """共通の有効画素で np.corrcoef と一致し、値が一定なら None を返す。"""
    x = np.array([0.1, 0.2, np.nan, 0.4, 0.8])
    y = np.array([30.0, 29.0, 28.0, np.nan, 25.0])
    expected = np.corrcoef([0.1, 0.2, 0.8], [30.0, 29.0, 25.0])[0, 1]

    assert sensitivity.pearson_on_common(x, y)["r"] == pytest.approx(expected)
    assert sensitivity.pearson_on_common(x, y)["count"] == 3
    assert sensitivity.pearson_on_common(np.ones(3), np.arange(3.0))["r"] is None


def test_summarize_by_ndvi_class_assigns_boundaries() -> None:
    """左端の階級のみ下限を含み、他は (下限, 上限]。範囲外と無効画素は数えない。"""
    ndvi = np.array([-1.0, 0.0, 0.1, 0.2, 0.5, 1.5, np.nan])
    delta_lst = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    delta_emissivity = np.array([0.01, 0.02, 0.03, 0.04, np.nan, 0.06, 0.07])

    table = sensitivity.summarize_by_ndvi_class(
        ndvi, delta_lst, delta_emissivity, bins=[-1.0, 0.0, 0.2, 1.0]
    )

    assert table["count"].tolist() == [2, 2, 1]
    assert table["delta_lst_mean"].tolist() == pytest.approx([1.5, 3.5, 5.0])
    assert table["delta_emissivity_mean"].iloc[1] == pytest.approx(0.035)
    assert np.isnan(table["delta_emissivity_mean"].iloc[2])


def test_summarize_by_ndvi_class_handles_empty_class() -> None:
    """画素の無い階級は件数 0・統計 NaN とする。"""
    table = sensitivity.summarize_by_ndvi_class(
        np.array([0.1]), np.array([1.0]), np.array([0.01]), bins=[0.0, 0.5, 1.0]
    )

    assert table["count"].tolist() == [1, 0]
    assert np.isnan(table["delta_lst_median"].iloc[1])


def test_summarize_by_ndvi_class_rejects_unsorted_bins() -> None:
    """境界が昇順でない場合はエラーにする。"""
    with pytest.raises(ValueError, match="昇順"):
        sensitivity.summarize_by_ndvi_class(
            np.array([0.1]), np.array([1.0]), np.array([0.0]), [0.5, 0.0]
        )


def test_run_lst_diff_writes_results(tmp_path: Path) -> None:
    """合成ラスタで再現確認・ΔLST・相関・図を出力する。"""
    reference = np.array([[30.0, 31.0], [np.nan, 34.0]])
    em0 = np.array([[30.5, 31.2], [np.nan, 33.0]])
    paths = {
        "reference_lst": write_raster(tmp_path / "ref.tif", [reference]),
        "indices": write_raster(
            tmp_path / "indices.tif",
            [np.array([[0.7, 0.5], [0.3, 0.1]])],
            descriptions=["NDVI"],
        ),
        "ndvi_lst": write_raster(tmp_path / "ndvi_lst.tif", [reference.copy()]),
        "ndvi_emissivity": write_raster(
            tmp_path / "ndvi_em.tif", [np.array([[0.98, 0.97], [np.nan, 0.95]])]
        ),
        "em0_lst": write_raster(tmp_path / "em0_lst.tif", [em0]),
        "em0_emissivity": write_raster(
            tmp_path / "em0_em.tif", [np.array([[0.97, 0.965], [np.nan, 0.96]])]
        ),
    }

    result_path = sensitivity.run_lst_diff(paths, tmp_path / "out", 1e-3, [-1.0, 0.4, 1.0])

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["reproduction_ndvi_vs_reference"]["reproduced"] is True
    assert result["delta_lst_c"]["count"] == 3
    assert result["delta_lst_c"]["mean"] == pytest.approx((-0.5 - 0.2 + 1.0) / 3)
    assert result["valid_pixels"]["em0_lst"] == 3
    assert [row["count"] for row in result["ndvi_classes"]] == [1, 2]
    assert (tmp_path / "out" / "lst_difference_map.png").exists()
    assert (tmp_path / "out" / "lst_difference_by_ndvi_class.png").exists()


def test_build_reference_paths_matches_export_layout() -> None:
    """既存・再出力のパスが GEE 出力スクリプトの配置先と一致する。"""
    paths = sensitivity.build_reference_paths("2022-09-06T03:23:58", "L8")

    assert paths["reference_lst"] == Path(
        "data/satellite/lst/2022/LST_Landsat8_20220906_032358Z.tif"
    )
    assert paths["indices"] == Path(
        "data/satellite/indices/2022/INDICES_Landsat8_20220906_032358Z.tif"
    )
    assert paths["em0_lst"] == Path(
        "data/satellite/lst_emissivity_sensitivity/em0/2022/LST_Landsat8_20220906_032358Z.tif"
    )
    assert paths["ndvi_emissivity"] == Path(
        "data/satellite/lst_emissivity_sensitivity/ndvi/2022/EMIS_Landsat8_20220906_032358Z.tif"
    )


# ---------------------------------------------------------------------------
# compare-runs
# ---------------------------------------------------------------------------


def test_rank_features_by_abs_and_ties() -> None:
    """標準化係数は絶対値で順位を付け、同値は特徴量名の順にする。"""
    values = {"NDVI": -0.6, "NDBI": 0.5, "ELEV": 0.5}

    assert sensitivity.rank_features(values, by_abs=True) == {"NDVI": 1, "ELEV": 2, "NDBI": 3}
    assert sensitivity.rank_features(values, by_abs=False) == {"ELEV": 1, "NDBI": 2, "NDVI": 3}


def test_compare_importance_reports_rank_changes() -> None:
    """寄与の差・順位の変化・上位の一致を求める。"""
    baseline = {"NDBI": 1.0, "NDVI": 0.5, "ELEV": 0.3, "POP": 0.1}
    variant = {"NDBI": 0.9, "NDVI": 0.2, "ELEV": 0.4, "POP": 0.1}

    table, summary = sensitivity.compare_importance(baseline, variant, by_abs=False, top_k=2)

    ndvi = table.set_index("feature").loc["NDVI"]
    assert ndvi["difference"] == pytest.approx(-0.3)
    assert ndvi["rank_change"] == 1
    assert summary["baseline_top"] == ["NDBI", "NDVI"]
    assert summary["variant_top"] == ["NDBI", "ELEV"]
    assert summary["top_same_set"] is False
    assert summary["spearman_rank_correlation"] == pytest.approx(0.8)


def test_compare_importance_rejects_different_features() -> None:
    """特徴量の集合が違うランどうしは比べない。"""
    with pytest.raises(ValueError, match="特徴量"):
        sensitivity.compare_importance({"NDVI": 1.0}, {"NDBI": 1.0}, by_abs=False)


def build_result(tmp_path: Path, name: str, r2_shift: float, ndvi_shap: float) -> Path:
    """比較用の最小限の results.json と fold 別指標 CSV を書く。

    Args:
        tmp_path: 出力先の一時ディレクトリ。
        name: ファイル名の接頭辞。
        r2_shift: R² に加える値（差の検算用）。
        ndvi_shap: NDVI の平均 |SHAP|。

    Returns:
        Path: results.json のパス。
    """
    folds_path = tmp_path / f"{name}_folds.csv"
    pd.DataFrame(
        {
            "fold": [1, 2],
            "train_size": [80, 80],
            "test_size": [20, 20],
            "linear_r2": [0.70 + r2_shift, 0.72 + r2_shift],
            "linear_rmse": [1.2, 1.3],
            "linear_mae": [0.9, 1.0],
            "rf_r2": [0.80 + r2_shift, 0.82 + r2_shift],
            "rf_rmse": [1.0, 1.1],
            "rf_mae": [0.7, 0.8],
        }
    ).to_csv(folds_path, index=False)
    importance = {"NDBI": 1.0, "NDVI": ndvi_shap}
    metrics = {"r2": 0.8 + r2_shift, "rmse": 1.0, "mae": 0.7}
    result: dict[str, Any] = {
        "dataset_path": f"data/output/datasets/{name}.gpkg",
        "features": ["NDBI", "NDVI"],
        "train_size": 80,
        "test_size": 20,
        "evaluation_cells": {"digest": "abc"},
        "run_parameters": {"random_state": 42, "rf_trees": 300},
        "random_split": {
            "linear_regression": {
                "metrics": metrics,
                "standardized_coefficients": {"NDBI": 0.5, "NDVI": -ndvi_shap},
            },
            "random_forest": {
                "metrics": metrics,
                "feature_importance": importance,
                "permutation_importance": importance,
            },
        },
        "spatial_cv": {
            "linear_regression": {"r2_mean": 0.71 + r2_shift, "rmse_mean": 1.25, "mae_mean": 0.95},
            "random_forest": {"r2_mean": 0.81 + r2_shift, "rmse_mean": 1.05, "mae_mean": 0.75},
            "outputs": {"fold_metrics_csv": str(folds_path)},
        },
        "shap": {"mean_abs_shap": importance},
        "filter_dropout": {"target_distribution": {"after": {"mean": 32.0, "std": 2.6}}},
    }
    result_path = tmp_path / f"{name}_results.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return result_path


def test_run_compare_runs_computes_variant_minus_baseline(tmp_path: Path) -> None:
    """差の向きは EM0 版 − NDVI 版で、fold ごとの対応のある差も出す。"""
    baseline = build_result(tmp_path, "baseline", r2_shift=0.0, ndvi_shap=0.5)
    variant = build_result(tmp_path, "variant", r2_shift=-0.02, ndvi_shap=0.2)

    result_path = sensitivity.run_compare_runs([("limited", baseline, variant)], tmp_path / "out")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    scenario = result["scenarios"]["limited"]
    rf_r2 = next(
        row
        for row in scenario["metrics"]
        if row["evaluation"] == "spatial_cv"
        and row["model"] == "random_forest"
        and row["metric"] == "r2_mean"
    )
    assert rf_r2["difference"] == pytest.approx(-0.02)
    assert scenario["spatial_cv_paired"]["metrics"]["rf_r2"]["mean_difference"] == pytest.approx(
        -0.02
    )
    assert scenario["importance"]["shap_mean_abs"]["top_same_order"] is True
    importance = pd.read_csv(tmp_path / "out" / "run_comparison_importance.csv")
    assert set(importance["family"]) == set(sensitivity.IMPORTANCE_FAMILIES)


def test_run_compare_runs_rejects_different_features(tmp_path: Path) -> None:
    """説明変数が違うランどうしは比べない。"""
    baseline = build_result(tmp_path, "baseline", r2_shift=0.0, ndvi_shap=0.5)
    variant = build_result(tmp_path, "variant", r2_shift=0.0, ndvi_shap=0.5)
    variant_result = json.loads(variant.read_text(encoding="utf-8"))
    variant_result["features"] = ["NDVI", "NDBI"]
    variant.write_text(json.dumps(variant_result), encoding="utf-8")

    with pytest.raises(ValueError, match="説明変数"):
        sensitivity.run_compare_runs([("limited", baseline, variant)], tmp_path / "out")


def test_run_compare_runs_rejects_duplicate_scenarios(tmp_path: Path) -> None:
    """同じシナリオ名を 2 回指定した場合はエラーにする。"""
    baseline = build_result(tmp_path, "baseline", r2_shift=0.0, ndvi_shap=0.5)

    with pytest.raises(ValueError, match="重複"):
        sensitivity.run_compare_runs(
            [("limited", baseline, baseline), ("limited", baseline, baseline)], tmp_path / "out"
        )


def test_argument_parser_requires_pairs_for_compare_runs() -> None:
    """compare-runs ではランの組の指定を必須にする。"""
    parser = sensitivity.build_argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["compare-runs", "--observation-datetime", "2022-09-06T03:23:58"])

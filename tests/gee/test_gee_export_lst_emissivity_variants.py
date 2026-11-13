"""gee_export_lst_emissivity_variants.py（放射率の感度分析用の出力）のテスト。

GEE に接続しない部分（観測日時の検証・出力名・配置先・点の選択・取得値の整形・
引数）を対象とする。GEE を呼ぶ処理は、関数を差し替えて受け渡し（放射率の切り替え・
出力先・上書き防止）のみを確かめる。
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

import src.gee.gee_export_lst_emissivity_variants as variants


def test_parse_observation_datetime_rejects_invalid_format() -> None:
    """秒まで含む ISO 形式以外は受け付けない（観測を 1 つに特定できないため）。"""
    with pytest.raises(ValueError, match="YYYY-MM-DDTHH:MM:SS"):
        variants.parse_observation_datetime("2022-09-06 03:23")


def test_build_observation_time_window_spans_one_second() -> None:
    """表記の秒を含み、次の秒を含まない範囲を作る。"""
    assert variants.build_observation_time_window("2022-09-06T03:23:58") == (
        "2022-09-06T03:23:58",
        "2022-09-06T03:23:59",
    )


def test_build_observation_time_window_crosses_year_end() -> None:
    """年末の最後の秒でも翌年の 0 時を終了にする。"""
    assert variants.build_observation_time_window("2022-12-31T23:59:59") == (
        "2022-12-31T23:59:59",
        "2023-01-01T00:00:00",
    )


def test_build_observation_day_range_returns_next_day() -> None:
    """当日と翌日を返す（filterDate の終了は含まない）。"""
    assert variants.build_observation_day_range("2023-02-28T03:23:05") == (
        "2023-02-28",
        "2023-03-01",
    )


def test_build_observation_token() -> None:
    """出力名用の `YYYYMMDD_HHMMSS` を作る。"""
    assert variants.build_observation_token("2022-09-06T03:23:58") == "20220906_032358"


def test_build_variant_drive_folder_separates_variants() -> None:
    """同じファイル名で出力するため、放射率ごとにフォルダ名が異なる。"""
    ndvi_folder = variants.build_variant_drive_folder("2022-09-06T03:23:58", "ndvi")
    em0_folder = variants.build_variant_drive_folder("2022-09-06T03:23:58", "em0")

    assert ndvi_folder == "MasterResearch_Data_LST_emissivity_ndvi_20220906_032358"
    assert em0_folder == "MasterResearch_Data_LST_emissivity_em0_20220906_032358"


def test_build_variant_drive_folder_rejects_unknown_variant() -> None:
    """未定義の放射率の種類はエラーにする。"""
    with pytest.raises(ValueError, match="未定義の放射率"):
        variants.build_variant_drive_folder("2022-09-06T03:23:58", "aster")


def test_build_export_plan_keeps_existing_file_name_format() -> None:
    """LST のファイル名は既存と同じ形式で、配置先は既存の data/satellite/lst/ と分ける。"""
    plan = variants.build_export_plan("2022-09-06T03:23:58", "L8")

    assert [entry["variant"] for entry in plan] == ["ndvi", "em0"]
    assert [entry["use_ndvi"] for entry in plan] == [True, False]
    assert {entry["lst_file_prefix"] for entry in plan} == {"LST_Landsat8_20220906_032358Z"}
    assert {entry["emissivity_file_prefix"] for entry in plan} == {"EMIS_Landsat8_20220906_032358Z"}
    assert plan[0]["local_lst_path"] == (
        "data/satellite/lst_emissivity_sensitivity/ndvi/2022/LST_Landsat8_20220906_032358Z.tif"
    )
    assert plan[1]["local_emissivity_path"] == (
        "data/satellite/lst_emissivity_sensitivity/em0/2022/EMIS_Landsat8_20220906_032358Z.tif"
    )
    assert all(not entry["local_lst_path"].startswith("data/satellite/lst/") for entry in plan)


def test_build_export_plan_uses_sensor_label() -> None:
    """Landsat 9 の観測ではファイル名のセンサ表記が Landsat9 になる。"""
    plan = variants.build_export_plan("2023-07-07T03:23:05", "L9")

    assert plan[0]["lst_file_prefix"] == "LST_Landsat9_20230707_032305Z"


def test_build_export_plan_rejects_unknown_sensor() -> None:
    """未定義のセンサは GEE に接続する前にエラーにする。"""
    with pytest.raises(ValueError):
        variants.build_export_plan("2022-09-06T03:23:58", "L7")


def test_select_reference_pixels_picks_only_finite_without_duplicates() -> None:
    """NaN の画素は選ばれず、同じ画素が重複しない。"""
    values = np.full((10, 10), np.nan)
    values[2:8, 3:9] = 30.0

    rows, cols = variants.select_reference_pixels(values, n_points=20, seed=0)

    assert np.isfinite(values[rows, cols]).all()
    assert len(set(zip(rows.tolist(), cols.tolist(), strict=True))) == 20


def test_select_reference_pixels_is_reproducible_with_seed() -> None:
    """同じシードなら同じ画素を選ぶ。"""
    values = np.arange(100, dtype="float64").reshape(10, 10)

    first = variants.select_reference_pixels(values, n_points=5, seed=42)
    second = variants.select_reference_pixels(values, n_points=5, seed=42)

    np.testing.assert_array_equal(first[0], second[0])
    np.testing.assert_array_equal(first[1], second[1])


@pytest.mark.parametrize("n_points", [0, 5])
def test_select_reference_pixels_rejects_invalid_count(n_points: int) -> None:
    """点の数が 1 未満、または有効画素数（ここでは 4）を超える場合はエラーにする。"""
    values = np.full((3, 3), np.nan)
    values[0, :2] = 1.0
    values[1, :2] = 1.0

    with pytest.raises(ValueError):
        variants.select_reference_pixels(values, n_points=n_points, seed=0)


def test_build_pixel_center_points_uses_pixel_centers() -> None:
    """座標は画素の左上ではなく中心になる（境界上の点が隣の画素に割り当たらないため）。"""
    transform = Affine(0.5, 0.0, 100.0, 0.0, -0.5, 20.0)

    points = variants.build_pixel_center_points(np.array([0, 2]), np.array([0, 1]), transform)

    assert points["point_id"].tolist() == [0, 1]
    assert points["x"].tolist() == pytest.approx([100.25, 100.75])
    assert points["y"].tolist() == pytest.approx([19.75, 18.75])


def test_read_reference_raster_keeps_nan_and_crs(tmp_path: Path) -> None:
    """無効値の NaN を保ったまま float64 で読み、CRS と変換を返す。"""
    raster_path = tmp_path / "lst.tif"
    data = np.array([[30.0, np.nan], [31.5, 32.0]], dtype="float64")
    transform = Affine(0.5, 0.0, 100.0, 0.0, -0.5, 20.0)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float64",
        crs=CRS.from_epsg(4326),
        transform=transform,
    ) as destination:
        destination.write(data, 1)

    values, read_transform, crs_text = variants.read_reference_raster(raster_path)

    np.testing.assert_array_equal(values, data)
    assert read_transform == transform
    assert crs_text == "EPSG:4326"


def test_read_reference_raster_rejects_missing_crs(tmp_path: Path) -> None:
    """CRS のないラスタは GEE 側で同じグリッドを指定できないためエラーにする。"""
    raster_path = tmp_path / "no_crs.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=1,
        width=1,
        count=1,
        dtype="float64",
        transform=Affine(1.0, 0.0, 0.0, 0.0, -1.0, 0.0),
    ) as destination:
        destination.write(np.array([[1.0]]), 1)

    with pytest.raises(ValueError, match="CRS"):
        variants.read_reference_raster(raster_path)


def test_parse_sampled_features_treats_missing_and_null_as_nan() -> None:
    """マスク画素で属性が欠けた場合・null の場合はどちらも NaN にし、point_id 順に並べる。"""
    features = [
        {"properties": {"point_id": 1, "lst_smw_ndvi": 30.0, "lst_smw_em0": None}},
        {
            "properties": {
                "point_id": 0,
                "lst_smw_ndvi": 31.0,
                "lst_smw_em0": 30.5,
                "lst_simple": 29.0,
            }
        },
    ]

    table = variants.parse_sampled_features(features, variants.SAMPLE_METHOD_COLUMNS)

    assert table["point_id"].tolist() == [0, 1]
    assert table.loc[0, "lst_simple"] == pytest.approx(29.0)
    assert np.isnan(table.loc[1, "lst_smw_em0"])
    assert np.isnan(table.loc[1, "lst_simple"])
    assert list(table.columns) == ["point_id", *variants.SAMPLE_METHOD_COLUMNS]


def test_parse_sampled_features_handles_empty_result() -> None:
    """結果が 0 件でも列と型を保った空の表を返す。"""
    table = variants.parse_sampled_features([], variants.SAMPLE_METHOD_COLUMNS)

    assert table.empty
    assert list(table.columns) == ["point_id", *variants.SAMPLE_METHOD_COLUMNS]
    assert table["lst_smw_ndvi"].dtype == "float64"


def test_parse_sampled_features_rejects_missing_point_id() -> None:
    """point_id のない Feature は照合できないためエラーにする。"""
    with pytest.raises(ValueError, match="point_id"):
        variants.parse_sampled_features([{"properties": {}}], variants.SAMPLE_METHOD_COLUMNS)


def test_merge_points_and_samples_rejects_mismatched_points() -> None:
    """取得値の点が要求と一致しない場合は、取りこぼしに気付けるようエラーにする。"""
    points = pd.DataFrame({"point_id": [0, 1], "x": [0.0, 1.0], "y": [0.0, 1.0]})
    samples = pd.DataFrame({"point_id": [0], "lst_smw_ndvi": [30.0]})

    with pytest.raises(ValueError, match="一致しません"):
        variants.merge_points_and_samples(points, samples)


def test_ensure_writable_blocks_overwrite(tmp_path: Path) -> None:
    """既存の出力は --overwrite がない限り上書きしない。"""
    existing = tmp_path / "out.csv"
    existing.write_text("x", encoding="utf-8")

    with pytest.raises(FileExistsError):
        variants.ensure_writable(existing, overwrite=False)
    variants.ensure_writable(existing, overwrite=True)
    variants.ensure_writable(tmp_path / "new.csv", overwrite=False)


def test_build_default_output_dir_separates_commands() -> None:
    """export と sample の既定の出力先は観測ごとに分かれ、互いに重ならない。"""
    assert variants.build_default_output_dir("export", "2022-09-06T03:23:58") == Path(
        "data/output/lst_emissivity_sensitivity/20220906_032358"
    )
    assert variants.build_default_output_dir("sample", "2023-07-07T03:23:05") == Path(
        "data/output/lst_emissivity_sensitivity/20230707_032305_method_check"
    )


def test_argument_parser_requires_reference_tif_for_sample() -> None:
    """sample では照合する既存 GeoTIFF の指定を必須にする。"""
    parser = variants.build_argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["sample", "--observation-datetime", "2023-07-07T03:23:05"])

    args = parser.parse_args(
        [
            "sample",
            "--observation-datetime",
            "2023-07-07T03:23:05",
            "--reference-tif",
            "ref.tif",
        ]
    )
    assert args.n_points == variants.DEFAULT_N_POINTS
    assert args.seed == variants.DEFAULT_SEED
    assert args.sensor == "L8"


class FakeImage:
    """`select`・`rename`・`addBands` の呼び出しを記録する、ee.Image の代用。"""

    def __init__(self, name: str) -> None:
        """名前を受け取り、バンド名の記録を初期化する。

        Args:
            name: 画像の識別名。
        """
        self.name = name
        self.band_names: list[str] = []

    def select(self, band: str) -> FakeImage:
        """選んだバンド名を引き継いだ画像を返す。

        Args:
            band: バンド名。

        Returns:
            FakeImage: 同じ識別名の画像。
        """
        return FakeImage(f"{self.name}.{band}")

    def rename(self, band: str) -> FakeImage:
        """バンド名を付けた画像を返す。

        Args:
            band: 新しいバンド名。

        Returns:
            FakeImage: 指定したバンド名を持つ画像。
        """
        renamed = FakeImage(self.name)
        renamed.band_names = [band]
        return renamed

    def addBands(self, other: FakeImage) -> FakeImage:  # noqa: N802 - ee.Image のメソッド名に合わせる
        """バンドを追加した画像を返す。

        Args:
            other: 追加する画像。

        Returns:
            FakeImage: 両方のバンド名を持つ画像。
        """
        combined = FakeImage(self.name)
        combined.band_names = [*self.band_names, *other.band_names]
        return combined


def test_build_sample_image_switches_emissivity(monkeypatch: pytest.MonkeyPatch) -> None:
    """NDVI 版と EM0 版で use_ndvi を切り替え、simple は雲マスク後の画像から作る。"""
    calls: list[dict[str, Any]] = []

    def fake_build_lst_image(*args: Any, **kwargs: Any) -> FakeImage:
        calls.append(kwargs)
        return FakeImage(f"lst_{kwargs['use_ndvi']}")

    monkeypatch.setattr(variants, "build_lst_image", fake_build_lst_image)
    monkeypatch.setattr(variants, "cloud_mask", lambda image: f"masked_{image}")
    simple_inputs: list[Any] = []

    def fake_calculate_lst_simple(image: Any) -> FakeImage:
        simple_inputs.append(image)
        return FakeImage("simple")

    monkeypatch.setattr(variants, "calculate_lst_simple", fake_calculate_lst_simple)

    image = variants.build_sample_image("raw", "toa", "roi", "L8")

    assert [call["use_ndvi"] for call in calls] == [True, False]
    assert all(call["sensor"] == "L8" for call in calls)
    assert simple_inputs == ["masked_raw"]
    assert image.band_names == list(variants.SAMPLE_METHOD_COLUMNS)


def patch_gee_context(monkeypatch: pytest.MonkeyPatch, roi_path: Path) -> None:
    """GEE の初期化・観測の取得を差し替える。

    Args:
        monkeypatch: pytest の monkeypatch。
        roi_path: 来歴に記録する ROI のパス。
    """
    monkeypatch.setattr(
        variants,
        "load_gee_context",
        lambda config_path: ({"output_epsg": 4326}, "roi", roi_path),
    )
    monkeypatch.setattr(
        variants, "fetch_observation", lambda observation, roi, sensor: ("raw", "toa")
    )
    monkeypatch.setattr(variants, "get_scene_index", lambda image: "LC08_127045_20220906")


def test_run_export_starts_tasks_per_variant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """放射率ごとに LST と放射率を別フォルダへ出力し、タスクの一覧を記録する。"""
    roi_path = tmp_path / "roi.shp"
    roi_path.write_text("dummy", encoding="utf-8")
    patch_gee_context(monkeypatch, roi_path)
    lst_calls: list[bool] = []
    monkeypatch.setattr(
        variants,
        "build_lst_image",
        lambda *args, **kwargs: lst_calls.append(kwargs["use_ndvi"]) or f"lst_{kwargs['use_ndvi']}",
    )
    lst_exports: list[dict[str, Any]] = []
    emissivity_exports: list[dict[str, Any]] = []
    monkeypatch.setattr(
        variants, "export_lst_to_drive", lambda **kwargs: lst_exports.append(kwargs)
    )
    monkeypatch.setattr(
        variants, "export_indices_to_drive", lambda **kwargs: emissivity_exports.append(kwargs)
    )

    summary_path = variants.run_export(
        observation_datetime_utc="2022-09-06T03:23:58",
        sensor="L8",
        config_path=tmp_path / "config.csv",
        output_dir=tmp_path / "out",
        overwrite=False,
    )

    assert lst_calls == [True, False]
    assert [call["image"] for call in lst_exports] == ["lst_True", "lst_False"]
    assert [call["folder_name"] for call in lst_exports] == [
        "MasterResearch_Data_LST_emissivity_ndvi_20220906_032358",
        "MasterResearch_Data_LST_emissivity_em0_20220906_032358",
    ]
    assert all(call["band_names"] == ["EM"] for call in emissivity_exports)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["scene_index"] == "LC08_127045_20220906"
    assert [entry["variant"] for entry in summary["exports"]] == ["ndvi", "em0"]
    assert "provenance" in summary


def test_run_export_does_not_start_tasks_when_summary_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """既存のタスク一覧がある場合は、GEE に接続する前に止める（二重出力を防ぐ）。"""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / variants.EXPORT_SUMMARY_NAME).write_text("{}", encoding="utf-8")

    def fail_if_called(config_path: Path) -> None:
        raise AssertionError("GEE に接続してはならない")

    monkeypatch.setattr(variants, "load_gee_context", fail_if_called)

    with pytest.raises(FileExistsError):
        variants.run_export(
            observation_datetime_utc="2022-09-06T03:23:58",
            sensor="L8",
            config_path=tmp_path / "config.csv",
            output_dir=output_dir,
            overwrite=False,
        )


def test_run_sample_writes_points_and_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """参照ラスタの有効画素の点について、3 方式の値と欠測数を保存する。"""
    raster_path = tmp_path / "lst.tif"
    data = np.array([[30.0, np.nan], [31.5, 32.0]], dtype="float64")
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float64",
        crs=CRS.from_epsg(4326),
        transform=Affine(0.5, 0.0, 100.0, 0.0, -0.5, 20.0),
    ) as destination:
        destination.write(data, 1)
    roi_path = tmp_path / "roi.shp"
    roi_path.write_text("dummy", encoding="utf-8")
    patch_gee_context(monkeypatch, roi_path)
    monkeypatch.setattr(variants, "build_sample_image", lambda *args: "image")
    requested: dict[str, Any] = {}

    def fake_sample(image: Any, points: pd.DataFrame, crs_text: str, transform: Affine) -> Any:
        requested["crs"] = crs_text
        requested["transform"] = transform
        samples = points[["point_id"]].copy()
        samples["lst_smw_ndvi"] = 30.0
        samples["lst_smw_em0"] = 29.0
        samples["lst_simple"] = np.nan
        return samples

    monkeypatch.setattr(variants, "sample_image_on_reference_grid", fake_sample)

    csv_path, summary_path = variants.run_sample(
        observation_datetime_utc="2023-07-07T03:23:05",
        sensor="L8",
        config_path=tmp_path / "config.csv",
        reference_tif=raster_path,
        output_dir=tmp_path / "out",
        n_points=3,
        seed=42,
        overwrite=False,
    )

    table = pd.read_csv(csv_path)
    assert len(table) == 3
    assert np.isfinite(data[table["row"], table["col"]]).all()
    assert requested["crs"] == "EPSG:4326"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["missing_counts"] == {"lst_smw_ndvi": 0, "lst_smw_em0": 0, "lst_simple": 3}
    assert summary["reference_transform"] == [0.5, 0.0, 100.0, 0.0, -0.5, 20.0]

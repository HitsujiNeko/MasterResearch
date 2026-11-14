"""gee_export_lst_emissivity_variants.py（放射率の感度分析用の出力）のテスト。

GEE に接続しない部分（観測日時の検証・出力名・配置先・引数）を対象とする。
GEE を呼ぶ処理は、関数を差し替えて受け渡し（放射率の切り替え・出力先・上書き防止）
のみを確かめる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import src.gee.gee_export_lst_emissivity_variants as variants


def test_parse_observation_datetime_rejects_invalid_format() -> None:
    """秒まで含む ISO 形式以外は受け付けない（観測を 1 つに特定できないため）。"""
    with pytest.raises(ValueError, match="YYYY-MM-DDTHH:MM:SS"):
        variants.parse_observation_datetime("2022-09-06 03:23")


@pytest.mark.parametrize("text", ["2022-9-6T03:23:58", "2022-09-06T3:23:58"])
def test_parse_observation_datetime_rejects_missing_zero_padding(text: str) -> None:
    """ゼロ埋めを省略した日時は拒否する（フォルダ名とファイル名が食い違うため）。"""
    with pytest.raises(ValueError, match="YYYY-MM-DDTHH:MM:SS"):
        variants.parse_observation_datetime(text)


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


def test_ensure_writable_blocks_overwrite(tmp_path: Path) -> None:
    """既存の出力は --overwrite がない限り上書きしない。"""
    existing = tmp_path / "out.csv"
    existing.write_text("x", encoding="utf-8")

    with pytest.raises(FileExistsError):
        variants.ensure_writable(existing, overwrite=False)
    variants.ensure_writable(existing, overwrite=True)
    variants.ensure_writable(tmp_path / "new.csv", overwrite=False)


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


def test_main_uses_observation_directory_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """出力先を指定しない場合は、観測日時ごとのディレクトリに記録する。"""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(variants, "run_export", lambda **kwargs: calls.append(kwargs))

    variants.main(["--observation-datetime", "2022-09-06T03:23:58"])

    assert calls[0]["output_dir"] == Path("data/output/lst_emissivity_sensitivity/20220906_032358")
    assert calls[0]["sensor"] == "L8"
    assert calls[0]["overwrite"] is False

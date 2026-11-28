"""black_marble/product.py（Black Marble 年次プロダクトの定義）のテスト。

取得・変換・サマリーの各モジュールが共有する定義そのものの整合性を確かめる。
定義を使う側のテスト（test_conversion.py 等）は定義に合わせて期待値を作るため、
定義自体の取り違えはそちらでは検出できない。
"""

from __future__ import annotations

from src.common.raster_area import DEFAULT_RASTER_NODATA
from src.preprocessing.black_marble import product


def test_band_names_are_unique() -> None:
    """入力の SDS 名と出力バンド名に重複が無い（辞書化で値が潰れるのを防ぐ）。"""
    sds_names = [band.sds_name for band in product.BAND_DEFINITIONS]
    output_names = [band.output_name for band in product.BAND_DEFINITIONS]

    assert len(sds_names) == len(set(sds_names))
    assert len(output_names) == len(set(output_names))


def test_primary_band_is_first_and_a_saturation_target() -> None:
    """被覆率を代表させる主バンドが band 1 にあり、飽和評価の対象になっている。"""
    first = product.BAND_DEFINITIONS[0]

    assert first.output_name == product.PRIMARY_BAND_NAME
    assert first.is_saturation_target is True


def test_saturation_targets_are_radiance_bands_only() -> None:
    """飽和評価の対象は放射輝度の合成バンドに限られ、観測回数・標準偏差は対象外になる。"""
    for band in product.BAND_DEFINITIONS:
        if band.is_saturation_target:
            assert band.unit == product.RADIANCE_UNIT
    excluded = {"near_nadir_num", "near_nadir_std"}
    for band in product.BAND_DEFINITIONS:
        if band.output_name in excluded:
            assert band.is_saturation_target is False
    assert excluded <= {band.output_name for band in product.BAND_DEFINITIONS}


def test_product_constants() -> None:
    """年次プロダクトの日付・無効値・提供開始年が取得の前提どおりである。"""
    assert product.PRODUCT_NAME == "VNP46A4"
    assert product.ANNUAL_DAY_OF_YEAR == "001"
    assert product.OUTPUT_NODATA == DEFAULT_RASTER_NODATA
    assert product.FIRST_AVAILABLE_YEAR == 2012

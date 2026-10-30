"""NASA Black Marble 年次プロダクト（VNP46A4）の定義。

製品名・アーカイブ番号・提供開始年と、出力 GeoTIFF のバンド構成・無効値を置く。
取得・変換・サマリーの各モジュールが共有する定義はここに集める。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.common.raster_area import DEFAULT_RASTER_NODATA

LAADS_ARCHIVE_SET = "5200"
PRODUCT_NAME = "VNP46A4"
# 年次プロダクトの day-of-year は常に 001
ANNUAL_DAY_OF_YEAR = "001"

OUTPUT_NODATA = DEFAULT_RASTER_NODATA
FIRST_AVAILABLE_YEAR = 2012

RADIANCE_UNIT = "nW·cm⁻²·sr⁻¹"
# データ被覆率を代表させるバンド。Black Marble の標準的な代表値。
PRIMARY_BAND_NAME = "ntl_near_nadir"


@dataclass(frozen=True)
class BandDefinition:
    """出力 GeoTIFF の 1 バンド分の定義。"""

    sds_name: str
    output_name: str
    unit: str
    description: str
    # 飽和評価の対象とするか。放射輝度そのものを表す合成バンドのみ True で、
    # 同じ単位でも意味が異なるバンド（標準偏差など）や観測回数は対象外にする
    is_saturation_target: bool


# 出力バンドの並び（1始まりのバンド番号に対応）
BAND_DEFINITIONS: tuple[BandDefinition, ...] = (
    BandDefinition(
        sds_name="NearNadir_Composite_Snow_Free",
        output_name="ntl_near_nadir",
        unit=RADIANCE_UNIT,
        description=(
            "近直下視（視野角 0-20°）の年次夜間光。月光・大気・BRDF 補正済みで、"
            "Black Marble の標準的な代表値"
        ),
        is_saturation_target=True,
    ),
    BandDefinition(
        sds_name="AllAngle_Composite_Snow_Free",
        output_name="ntl_all_angle",
        unit=RADIANCE_UNIT,
        description="全視野角を用いた年次夜間光。観測数が多いぶん安定するが視野角の影響を含む",
        is_saturation_target=True,
    ),
    BandDefinition(
        sds_name="NearNadir_Composite_Snow_Free_Num",
        output_name="near_nadir_num",
        unit="観測回数",
        description="近直下視の合成に用いた観測数。少ない画素は値の信頼度が低い",
        is_saturation_target=False,
    ),
    BandDefinition(
        sds_name="NearNadir_Composite_Snow_Free_Std",
        output_name="near_nadir_std",
        unit=RADIANCE_UNIT,
        description="近直下視の合成に用いた観測値の標準偏差。年内のばらつきの指標",
        is_saturation_target=False,
    ),
)

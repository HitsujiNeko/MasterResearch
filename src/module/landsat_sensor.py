"""
Landsat センサ（Landsat 8 / Landsat 9）の定義を集約するモジュール

GEE のコレクション ID・出力ファイル名のラベルをセンサごとに 1 か所で管理し、
LST・衛星指標の算出スクリプトとシーン探索スクリプトから共通に参照する。
`ee` に依存しない純粋な Python のモジュールとし、単体テストの対象とする。

Landsat 9（OLI-2 / TIRS-2）のバンド構成（SR_B1〜SR_B7・ST_B10・QA_PIXEL、
TOA の B10）は Landsat 8 と同一であり、センサ間で異なるのはコレクション ID と
SMW 係数のみである（SMW 係数は `src.module.lst_smw` で管理する）。

参考:
    - GEE データカタログ LANDSAT/LC08/C02/T1_L2, LANDSAT/LC09/C02/T1_L2
    - GEE データカタログ LANDSAT/LC08/C02/T1_TOA, LANDSAT/LC09/C02/T1_TOA
"""

from __future__ import annotations

import math

# 既定のセンサ。既存の呼び出し元・`sensors` 列を持たない設定 CSV の挙動を変えないため L8 とする
DEFAULT_SENSOR = "L8"

# 設定 CSV の `sensors` 列でセンサを区切る文字
SENSOR_SEPARATOR = ";"

# センサごとの定義（toa: TOA コレクション ID、sr: 地表面反射率コレクション ID、
# label: 出力ファイル名・結果 CSV に用いるラベル）
LANDSAT_SENSORS: dict[str, dict[str, str]] = {
    "L8": {
        "toa": "LANDSAT/LC08/C02/T1_TOA",
        "sr": "LANDSAT/LC08/C02/T1_L2",
        "label": "Landsat8",
    },
    "L9": {
        "toa": "LANDSAT/LC09/C02/T1_TOA",
        "sr": "LANDSAT/LC09/C02/T1_L2",
        "label": "Landsat9",
    },
}


def validate_sensor(sensor: str) -> str:
    """センサ名が定義済みであることを確認する

    Args:
        sensor: センサ名（"L8" / "L9"）

    Returns:
        確認済みのセンサ名（入力と同じ値）

    Raises:
        ValueError: 未定義のセンサ名の場合
    """
    if sensor not in LANDSAT_SENSORS:
        supported = ", ".join(LANDSAT_SENSORS)
        raise ValueError(f"未対応のセンサです: {sensor!r}（対応: {supported}）")
    return sensor


def parse_sensors(value: object) -> list[str]:
    """設定 CSV の `sensors` 列の値を解釈してセンサ名のリストを返す

    値は `;` 区切り（例: "L8;L9"）とする。前後の空白と大文字・小文字の違いは
    許容し、重複は最初の出現順を保って除く。列がない・欠損（None / NaN）・空欄の
    場合は既定の `["L8"]` を返す。

    Args:
        value: `sensors` 列の値（pandas で読み込んだ NaN を含みうる）

    Returns:
        センサ名のリスト（例: ["L8", "L9"]）

    Raises:
        ValueError: 未定義のセンサ名を含む場合
    """
    if value is None:
        return [DEFAULT_SENSOR]
    if isinstance(value, float) and math.isnan(value):
        return [DEFAULT_SENSOR]

    sensors: list[str] = []
    for token in str(value).split(SENSOR_SEPARATOR):
        sensor = token.strip().upper()
        if not sensor:
            continue
        validate_sensor(sensor)
        if sensor not in sensors:
            sensors.append(sensor)

    return sensors if sensors else [DEFAULT_SENSOR]


def get_sensor_label(sensor: str) -> str:
    """出力ファイル名・結果 CSV に用いるセンサのラベルを返す

    Args:
        sensor: センサ名（"L8" / "L9"）

    Returns:
        ラベル（"Landsat8" / "Landsat9"）

    Raises:
        ValueError: 未定義のセンサ名の場合
    """
    return LANDSAT_SENSORS[validate_sensor(sensor)]["label"]


def get_collection_id(sensor: str, level: str) -> str:
    """センサと処理レベルに対応する GEE コレクション ID を返す

    Args:
        sensor: センサ名（"L8" / "L9"）
        level: 処理レベル（"toa": TOA、"sr": 地表面反射率 Level-2）

    Returns:
        GEE コレクション ID

    Raises:
        ValueError: 未定義のセンサ名・処理レベルの場合
    """
    definition = LANDSAT_SENSORS[validate_sensor(sensor)]
    if level not in ("toa", "sr"):
        raise ValueError(f"未対応の処理レベルです: {level!r}（対応: toa, sr）")
    return definition[level]

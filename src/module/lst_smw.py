"""
SMW（Statistical Mono-Window）手法によるLST計算モジュール

本モジュールは以下の論文の手法に基づく：
Ermida, S.L., Soares, P., Mantas, V., Göttsche, F.-M., Trigo, I.F., 2020.
Google Earth Engine open-source code for Land Surface Temperature estimation
from the Landsat series. Remote Sensing, 12 (9), 1471.
https://doi.org/10.3390/rs12091471

"""

import warnings

import ee

from src.module.landsat_sensor import DEFAULT_SENSOR, validate_sensor

# SMW係数テーブル（論文のSMW_coefficients.jsより。原本は src/js/modules/SMW_coefficients.js）
# 各行は (TPWpos, A, B, C)。TPWposはTPWを6 mm刻みで区分した0〜9の位置インデックス
SMW_COEFFICIENTS: dict[str, list[tuple[int, float, float, float]]] = {
    "L8": [
        (0, 0.9751, -205.8929, 212.7173),
        (1, 1.0090, -232.2750, 230.5698),
        (2, 1.0541, -253.1943, 238.9548),
        (3, 1.1282, -279.4212, 244.0772),
        (4, 1.1987, -307.4497, 251.8341),
        (5, 1.3205, -348.0228, 257.2740),
        (6, 1.4540, -393.1718, 263.5599),
        (7, 1.6350, -451.0790, 268.9405),
        (8, 1.5468, -429.5095, 275.0895),
        (9, 1.9403, -547.2681, 277.9953),
    ],
    "L9": [
        (0, 0.9751, -206.2187, 213.0526),
        (1, 1.0093, -232.7408, 230.9401),
        (2, 1.0539, -253.4430, 239.2572),
        (3, 1.1267, -279.1685, 244.2379),
        (4, 1.1961, -306.7961, 251.8873),
        (5, 1.3155, -346.5312, 257.2174),
        (6, 1.4463, -390.7794, 263.3479),
        (7, 1.6229, -447.2745, 268.5970),
        (8, 1.5396, -427.0904, 274.6380),
        (9, 1.9223, -541.7084, 277.4964),
    ],
}


def get_smw_coefficients(sensor: str = DEFAULT_SENSOR) -> list[tuple[int, float, float, float]]:
    """センサに対応するSMW係数テーブルを返す

    Args:
        sensor: センサ名（"L8" / "L9"）

    Returns:
        (TPWpos, A, B, C) のリスト（TPWposの昇順・10行）

    Raises:
        ValueError: 未定義のセンサ名、またはSMW係数が未登録のセンサの場合
    """
    validate_sensor(sensor)
    if sensor not in SMW_COEFFICIENTS:
        raise ValueError(f"SMW係数が未登録のセンサです: {sensor!r}")
    return SMW_COEFFICIENTS[sensor]


def compute_ndvi(image: ee.Image) -> ee.Image:
    """NDVI = (NIR - Red) / (NIR + Red)
    Args:
        image: Landsat 8画像

    Returns:
        NDVIバンドを追加した画像
    """
    # スケーリング係数を適用
    nir = image.select("SR_B5").multiply(0.0000275).add(-0.2)
    red = image.select("SR_B4").multiply(0.0000275).add(-0.2)

    ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")

    return image.addBands(ndvi)


def compute_fvc(image: ee.Image) -> ee.Image:
    """Fractional Vegetation Cover（植生被覆率）を計算

    FVC = ((NDVI - NDVI_bare) / (NDVI_veg - NDVI_bare))²
    NDVI_bare = 0.2, NDVI_veg = 0.86

    Args:
        image: NDVI計算済みの画像

    Returns:
        FVCバンドを追加した画像
    """
    ndvi = image.select("NDVI")
    fvc = ndvi.subtract(0.2).divide(0.86 - 0.2).pow(2)
    # 0-1の範囲にクリップ
    fvc = fvc.where(fvc.lt(0.0), 0.0).where(fvc.gt(1.0), 1.0)

    return image.addBands(fvc.rename("FVC"))


def get_aster_emissivity(image: ee.Image, roi: ee.Geometry) -> ee.Image:
    """ASTER放射率データを取得し、植生補正を適用して裸地放射率を算出

    1. ASTER NDVIからFVCを計算
    2. 裸地放射率 = (ε_ASTER - 0.99×FVC) / (1-FVC) で植生影響を除去
    3. Landsat 8用の係数で補間: ε = c13×ε13 + c14×ε14 + c

    Landsat 9 も同じ係数を用いる。参照実装の compute_emissivity.js は L4/L5/L7 以外を
    L8 の係数で処理し、Landsat_LST.js は L9 もこの経路で処理するため。

    Args:
        image: Landsat 8 / Landsat 9画像
        roi: 対象地域

    Returns:
        裸地放射率バンドを追加した画像
    """
    aster = ee.Image("NASA/ASTER_GED/AG100_003").clip(roi)

    # ASTER NDVIからFVCを計算（論文のASTER_bare_emiss.js）
    aster_ndvi = aster.select("ndvi").multiply(0.01)  # スケール係数
    aster_fvc = aster_ndvi.subtract(0.2).divide(0.86 - 0.2).pow(2)
    aster_fvc = aster_fvc.where(aster_fvc.lt(0.0), 0.0).where(aster_fvc.gt(1.0), 1.0)

    # 裸地放射率を植生補正で算出: ε_bare = (ε - 0.99×FVC) / (1-FVC)
    em13 = aster.select("emissivity_band13").multiply(0.001)
    em14 = aster.select("emissivity_band14").multiply(0.001)

    em_bare_band13 = aster.expression("(EM - 0.99*fvc)/(1.0-fvc)", {"EM": em13, "fvc": aster_fvc})

    em_bare_band14 = aster.expression("(EM - 0.99*fvc)/(1.0-fvc)", {"EM": em14, "fvc": aster_fvc})

    # Landsat 8用の係数で補間（論文のcompute_emissivity.js）
    # c13=0.6820, c14=0.2578, c=0.0584
    em_bare = (
        em_bare_band13.multiply(0.6820)
        .add(em_bare_band14.multiply(0.2578))
        .add(0.0584)
        .rename("EM_bare")
    )

    # ASTER emissivity without vegetation correction (EM0)
    em0 = em13.multiply(0.6820).add(em14.multiply(0.2578)).add(0.0584).rename("EM0")

    return image.addBands(em_bare).addBands(em0)


def compute_emissivity(image: ee.Image, use_ndvi: bool = True) -> ee.Image:
    """FVCとASTER裸地放射率から動的放射率を計算

    ε = 0.99 × FVC + (1 - FVC) × ε_bare
    水域の放射率: 0.99（QA_PIXELビット7で検出）
    雪域の放射率: 0.989（QA_PIXELビット5で検出）

    Args:
        image: FVCとEM_bareを含む画像

    Returns:
        放射率バンドを追加した画像
    """
    fvc = image.select("FVC")
    em_bare = image.select("EM_bare")
    em0 = image.select("EM0")
    qa = image.select("QA_PIXEL")

    emd = ee.Image(0.99).multiply(fvc).add(ee.Image(1.0).subtract(fvc).multiply(em_bare))
    emissivity = emd if use_ndvi else em0

    # 水域の検出と放射率の処方値設定（QA_PIXELビット7）
    emissivity = emissivity.where(qa.bitwiseAnd(1 << 7), 0.99)
    # 雪域の検出と放射率の処方値設定（QA_PIXELビット5）
    emissivity = emissivity.where(qa.bitwiseAnd(1 << 5), 0.989)

    return image.addBands(emissivity.rename("EM"))


def get_atmospheric_water_vapor(image: ee.Image, roi: ee.Geometry) -> ee.Image:
    """NCEP再解析データから大気水蒸気量（TPW）を取得

    NCEPデータは6時間ごと（0:00, 6:00, 12:00, 18:00 UTC）なので、
    Landsat取得時刻に対して線形補間を実行

    Args:
        image: Landsat 8画像
        roi: 対象地域

    Returns:
        TPWバンドを追加した画像
    """
    date = ee.Date(image.get("system:time_start"))

    # 元の JavaScript 実装と同じく、当日 UTC のみを対象にする
    year = ee.Number.parse(date.format("yyyy"))
    month = ee.Number.parse(date.format("MM"))
    day = ee.Number.parse(date.format("dd"))
    date_start = ee.Date.fromYMD(year, month, day)
    date_end = date_start.advance(1, "day")

    # DateDistを計算する関数
    def compute_date_dist(ncep_image):
        return ncep_image.set(
            "DateDist", ee.Number(ncep_image.get("system:time_start")).subtract(date.millis()).abs()
        )

    # `NCEP_RE/surface_wv` は deprecated だが、SMW法の再現性維持のため継続利用する。
    # 他の警告は維持しつつ、この既知警告のみ局所的に抑制する。
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*Attention required for NCEP_RE/surface_wv.*",
            category=DeprecationWarning,
        )
        ncep_collection = (
            ee.ImageCollection("NCEP_RE/surface_wv")
            .filterDate(date_start, date_end)
            .map(compute_date_dist)
        )

    # 最も近い2つのNCEP画像を取得
    closest = ncep_collection.sort("DateDist").toList(2)

    # データが存在しない場合は-999.0を設定（後でマスクされる）
    tpw1 = ee.Image(
        ee.Algorithms.If(
            closest.size().eq(0),
            ee.Image.constant(-999.0),
            ee.Image(closest.get(0)).select("pr_wtr"),
        )
    )

    tpw2 = ee.Image(
        ee.Algorithms.If(
            closest.size().eq(0),
            ee.Image.constant(-999.0),
            ee.Algorithms.If(closest.size().eq(1), tpw1, ee.Image(closest.get(1)).select("pr_wtr")),
        )
    )

    # 時間的な重み計算（21600000ミリ秒 = 6時間）
    time1 = ee.Number(
        ee.Algorithms.If(
            closest.size().eq(0), 1.0, ee.Number(tpw1.get("DateDist")).divide(21600000)
        )
    )

    time2 = ee.Number(
        ee.Algorithms.If(
            closest.size().lt(2), 0.0, ee.Number(tpw2.get("DateDist")).divide(21600000)
        )
    )

    # 線形補間: tpw = tpw1*time2 + tpw2*time1
    tpw = tpw1.expression(
        "tpw1*time2 + tpw2*time1", {"tpw1": tpw1, "tpw2": tpw2, "time1": time1, "time2": time2}
    ).clip(image.geometry())

    # TPW範囲に基づく位置インデックス（TPWpos）の計算
    tpw_pos = tpw.expression(
        "(TPW>0 && TPW<=6) ? 0"
        + ": (TPW>6 && TPW<=12) ? 1"
        + ": (TPW>12 && TPW<=18) ? 2"
        + ": (TPW>18 && TPW<=24) ? 3"
        + ": (TPW>24 && TPW<=30) ? 4"
        + ": (TPW>30 && TPW<=36) ? 5"
        + ": (TPW>36 && TPW<=42) ? 6"
        + ": (TPW>42 && TPW<=48) ? 7"
        + ": (TPW>48 && TPW<=54) ? 8"
        + ": (TPW>54) ? 9"
        + ": 0",
        {"TPW": tpw},
    ).clip(image.geometry())

    # TPWとTPWposの両方を追加
    return image.addBands(tpw.rename("TPW")).addBands(tpw_pos.rename("TPWpos"))


def apply_smw_algorithm(image: ee.Image, sensor: str = DEFAULT_SENSOR) -> ee.Image:
    """SMWアルゴリズムでLSTを計算（完全実装）

    論文の実装方法に基づく（SMWalgorithm.js）：
    1. TPWposを使用してLUT係数を各ピクセルに適用
    2. SMW式でLSTを計算: LST = A * Tb/ε + B/ε + C

    Args:
        image: B10（TOA輝度温度）、EM（放射率）、TPWposを含む画像
        sensor: 係数テーブルを選ぶセンサ名（"L8" / "L9"）

    Returns:
        LSTバンドを追加した画像

    Raises:
        ValueError: 未定義のセンサ名の場合
    """
    # バンドを選択
    bt = image.select("B10")  # TOA輝度温度（K）
    em = image.select("EM")
    tpw = image.select("TPW")
    tpw_pos = image.select("TPWpos")

    # センサ別のSMW係数テーブル（論文のSMW_coefficients.jsより）
    coeff_smw = ee.FeatureCollection(
        [
            ee.Feature(None, {"TPWpos": tpw_pos_value, "A": a, "B": b, "C": c})
            for tpw_pos_value, a, b, c in get_smw_coefficients(sensor)
        ]
    )

    # ルックアップテーブルを作成
    def get_lookup_table(fc, prop_1, prop_2):
        """FeatureCollectionからルックアップテーブルを作成"""
        reducer = ee.Reducer.toList().repeat(2)
        lookup = fc.reduceColumns(reducer, [prop_1, prop_2])
        return ee.List(lookup.get("list"))

    A_lookup = get_lookup_table(coeff_smw, "TPWpos", "A")
    B_lookup = get_lookup_table(coeff_smw, "TPWpos", "B")
    C_lookup = get_lookup_table(coeff_smw, "TPWpos", "C")

    # remap()を使ってTPWposに対応する係数を各ピクセルに適用
    A_img = tpw_pos.remap(A_lookup.get(0), A_lookup.get(1), 0.0).resample("bilinear")
    B_img = tpw_pos.remap(B_lookup.get(0), B_lookup.get(1), 0.0).resample("bilinear")
    C_img = tpw_pos.remap(C_lookup.get(0), C_lookup.get(1), 0.0).resample("bilinear")

    # SMW式でLSTを計算: LST = A * Tb/ε + B/ε + C
    lst = image.expression(
        "A*Tb1/em1 + B/em1 + C", {"A": A_img, "B": B_img, "C": C_img, "em1": em, "Tb1": bt}
    )

    # TPWが負の値（データなし）の場合はマスク
    lst = lst.updateMask(tpw.lt(0).Not())

    # ケルビンから摂氏に変換
    lst_celsius = lst.subtract(273.15)

    # LSTバンドを追加（摂氏温度）
    return image.addBands(lst_celsius.rename("LST"))


def calculate_lst_smw(
    image_sr: ee.Image,
    image_toa: ee.Image,
    roi: ee.Geometry,
    use_ndvi: bool = True,
    sensor: str = DEFAULT_SENSOR,
) -> ee.Image:
    """SMW手法でLST計算（全ステップ統合）

    Args:
        image_sr: Landsat 8 / Landsat 9 Surface Reflectance画像
        image_toa: Landsat 8 / Landsat 9 TOA画像（B10バンド用）
        roi: 対象地域
        use_ndvi: NDVIによる動的放射率を用いるか（Falseの場合はASTER放射率EM0を用いる）
        sensor: SMW係数を選ぶセンサ名（"L8" / "L9"）。画像の取得元センサと一致させる

    Returns:
        LSTバンドを追加した画像

    Raises:
        ValueError: 未定義のセンサ名の場合
    """
    # ステップ1-5: SRコレクションで処理
    image = compute_ndvi(image_sr)
    image = compute_fvc(image)
    image = get_aster_emissivity(image, roi)
    image = compute_emissivity(image, use_ndvi=use_ndvi)
    image = get_atmospheric_water_vapor(image, roi)

    # TOAコレクションからB10バンドを追加（熱赤外TOA輝度温度）
    image = image.addBands(image_toa.select("B10"))

    # ステップ6: SMWアルゴリズム適用
    image = apply_smw_algorithm(image, sensor=sensor)

    return image

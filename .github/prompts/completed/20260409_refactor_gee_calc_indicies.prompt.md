---
agent: agent
---
完了：2026年4月9日

# タスク: 衛星から指標を算出するPythonソースコードの修正

## 概要
gee_calc_satellite_indices.py は、Google Earth Engine（GEE）を用いて、衛星画像からNDVI, NDWI, NDBIを算出するPythonソースコードです。
gee_calc_LST.py はLSTを出力する際、hanoi のROI でクリップして出力しています。一方、gee_calc_satellite_indices.py は、ROI でクリップせずに出力しています。

これにより、以下の問題を引き起こしています。

- エクスポートするGeoTIFFのサイズが大きくなり、Google Driveの容量を圧迫する
- LSTと衛星指標の範囲が異なり、分析の前処理で余計な作業が発生する

このタスクでは、gee_calc_satellite_indices.py を修正して、LSTと同様にROIでクリップして出力するようにします。


## タスク詳細
gee_calc_LST.py を参照して、ROIでクリップする処理をgee_calc_satellite_indices.py に追加する



## 要件
- 出力されるGeoTIFFは、LSTと同様にROIでクリップされたものとする

## 関連ファイル
- src\gee\gee_calc_satellite_indices.py
Google Earth Engine（GEE）を用いて、衛星画像からNDVI, NDWI, NDBIを算出するPythonソースコード。
こちらが修正対象

- src\gee\gee_calc_LST.py
Google Earth Engine（GEE）を用いて、衛星画像から地表面温度（LST）を算出するPythonソースコード。
---

共通ルールは以下のファイルを参照すること
.github\copilot-instructions.md
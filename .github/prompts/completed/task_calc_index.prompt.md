---
agent: agent
---

# タスク
指標 Index を算出するPythonスクリプトを作成してください。


## 概要
gpkg形式の地理空間データファイルを読み込み、各フィーチャの属性情報を解析・翻訳するPythonスクリプトを作成します。スクリプトは以下の要件を満たす必要があります。


## 背景
以前、Landsat8衛星画像を用いて地表面温度を算出するプログラムを作成しました。このタスクは完了しました。今後の研究として
、地表面温度に加えて、NDVIやNDBIなどの指標も同時に算出する必要があります。

## 要件
- Google Earth Engine (GEE) を使用して、NDVI（Normalized Difference Vegetation Index）およびNDBI（Normalized Difference Built-up Index）を算出します。
- 既存のLST算出プログラムの実行時に、指標indexesを同時に算出できるように統合する。
- 入力ファイルに、output_indexがtrueの場合に指標を算出するオプションを追加する。
- 算出した指標はtiff形式でエクスポートする。
- 算出した指標の最大値、最小値、平均値をCSVファイルに保存する。
- 指標は今後、NDVI、NDBIに加えて他の指標も追加できるように設計する。
- 可能であれば、gee_calc_LST.pyから独立し、指標のみの算出も可能な設計にする。
- マスク処理はLSTと同様に実施する。



## 懸念点

## 関連ファイル
1. src\gee_calc_LST.py
LST算出プログラムのメインスクリプト。
2. src\module\lst_smw.py
LST算出に使用する関数群を定義したモジュールファイル。
3. data\input\gee_calc_LST_info.csv
こちらにgee_calc_LST.pyの実行に必要なパラメータが記載されています。
→　本タスクでは、output_indexを追加してください。


# タスク実行時の共通ルール
ワークスペースの任意のファイルを、適宜読み取りタスクを実行してください。
必ずコーディング規約を遵守してください。
.github\prompts\CodingRule.md


# Pythonコーディング規約（研究プロジェクト用）
以下の相対パスの.mdファイルを参照してください。
.github\prompts\CodingRule.md

# 研究計画書
以下の相対パスの.mdファイルを参照してください。
.github\prompts\research_guide.md

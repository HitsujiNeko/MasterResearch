---
agent: agent
---

# タスク: Fortran コードを Python に移植する

## 目的
DEM 生成に利用していた `src/fortran/bs_horizon.f` を Python に移植し、
コードの可読性と再利用性を高める。

## タスク詳細
`src/fortran/bs_horizon.f` の数値ロジックを Python に移植する。
移植後は、Fortran の対話実行ではなく CLI から同等の処理を実行できるようにする。

対象コードは、標高点データと走向傾斜データを用いて BS-Horizon により DEM を補間する
プログラムであり、以下を満たすことを要件とする。

- Fortran と同じ入力概念を維持する
  - 標高点: `id x y z lm`
  - 走向傾斜: `id x y z trend dip`
  - 終端行: `abs(x) > 1e9`
- 標高制約、走向傾斜制約、平滑化項、反復ペナルティを Python で再現する
- DEM 出力と係数出力をファイルに保存できるようにする
- コメントと docstring を付け、処理の意味が追えるようにする

## 入力データ・入力ファイル
- `src/fortran/bs_horizon.f`

## 期待される成果物
- `src/preprocessing/bs_horizon.py`

## 関連ドキュメント
- `docs/02_methods/CodingRule.md`
- `CLAUDE.md`

---

## 完了時の記録

**完了日**: 2026-06-01  
**ステータス**: 完了

### 実施内容
- `src/fortran/bs_horizon.f` を `src/preprocessing/bs_horizon.py` に移植した
- 標高点ファイルと走向傾斜ファイルを読み込む CLI を追加した
- Fortran と同じ DEM テキスト出力形式、および係数出力形式を実装した
- 帯行列の解法は Python 版として SciPy の対称帯行列ソルバを優先使用し、未使用時は移植した Cholesky 実装へ fallback する構成にした
- 平滑化項の行列組み立てと評価式は、Fortran の `setJtmp` / `Jtmp` を優先して一致させた
- 追加レビューを受けて、`setJtmp` のコピー更新と `Jtmp` の第2クロス項を Fortran どおりに修正した
- 等式-only と不等式制約ありで反復条件を分ける Fortran の制約を Python 側でも厳格に再現した
- コードレビュー: 全関数で Fortran と 1 対 1 対応、実装上の問題なしを確認した
- Fortran 版（gfortran/WSL）と Python 版を同一の 100 点合成データ（10×10 格子、単純傾斜平面）で実行し数値突合した
- `--config` オプションによる YAML パラメータファイル対応を追加した
- 標高ファイルの `lm` 列を省略可能にした（省略時は等式制約 lm=0 として扱う）
- 実データ（46,254点）で YAML 設定ファイルからの実行を確認した

### 成果物
- `src/preprocessing/bs_horizon.py`
- `data/BSHorizon/config/sample.yaml`（設定ファイルのサンプル）
- `environment.yml`（pyyaml を追加）

### 検証
- コードレビュー: 全サブルーチン（bspl, setbAh, setbAd, setJ, setJtmp, choles, Rhvalue, Rdvalue, Jvalue, Jtmp, cfout 相当）の実装を Fortran と照合
- Fortran（gfortran で WSL コンパイル・実行）と Python を同一パラメータで実行し比較
  - テストデータ: 100 点 (10×10 格子, x/y∈[0,9], z=100+2x+3y, lm=0)
  - パラメータ: mx=3, my=3, alpha=1000, m1=1, m2=1, 走向傾斜データなし
- 実データ（`data/BSHorizon/input/merge_DH_elevation_points.csv`, 46,254点）で YAML 設定から実行し完走を確認

### 検証結果
| 指標 | Fortran | Python | 差 |
|------|---------|--------|----|
| Rh | 2.2959E-04 | 2.29590E-04 | 0 |
| Jx | 3.5848E+01 | 3.58481E+01 | <1E-5 |
| Jy | 8.0658E+01 | 8.06581E+01 | <1E-5 |
| Q | 1.1675E+02 | 1.16752E+02 | <1E-3 |
| B-スプライン係数（36個）| — | — | 最大差 4E-7（浮動小数点精度内）|

- 全指標で 5 桁以上一致。差は Fortran (Cholesky) と Python (SciPy solveh_banded) の実装差による丸め誤差のみ

### 変更ファイル
- `src/preprocessing/bs_horizon.py`
- `environment.yml`（pyyaml 追加）
- `data/BSHorizon/config/sample.yaml`（新規）
- `.github/prompts/completed/20260601_convert_fortran_to_Python.prompt.md`

### 未対応・補足
- 実測データでの Fortran との数値突合は未実施（合成データでの一致を確認済み）
- `src/fortran/bs_horizon.f` は参照用として残した

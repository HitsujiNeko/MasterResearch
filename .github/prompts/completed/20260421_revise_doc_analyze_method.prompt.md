---
agent: agent
---

# タスク: ドキュメント修正

## 概要
研究の分析におけるドキュメントの内容を、最新の分析状況や研究の進捗に合わせて修正するタスクです。

主に更新が必要なドキュメントは以下の通りです。

- docs\03_results\satellite_only_20230707_initial_run.md
- docs\02_methods\analysis_workflow.md
- docs\03_results\data_preparation_status.md
- docs\02_methods\calc_urban_params_guide.md


## 背景
研究の分析に関するドキュメントが、現在の研究の進捗に追い付いていない状況にあり、ドキュメントの内容が古くなっているため、最新の分析状況や研究の進捗に合わせてドキュメントの内容を修正する必要があります。

## 現状の進捗状況
- 研究の軸は明確です。RQ1-RQ3 は research_guide.md で固まっています。

- 研究の分析は、Satelite Only /  Limited / Full の3段階で進めることが決まっています。Satellite Only は衛星データのみの分析、Limited は衛星データに加えて、オープンソースのGISデータを都市構造パラメータとして使用する分析、Full は衛星データに加えて、オープンソースと、測量由来のGISデータを都市構造パラメータとして使用する分析を指しています。
現在は Satellite Only の分析が完了し、その結果が docs\03_results\satellite_only_20230707_initial_run.md および docs\03_results\GIS_IDEAS_abstract.md に記載されています。Limited / Full の分析はまだ完了していません。

- 測量由来のGISデータは、整理・加工・調査中であり、gpkgの確認結果.mdおよび DGNファイル内容確定結果.md に記載されています。



## タスク詳細
それぞれのドキュメントの修正内容を以下に示します。

- docs\03_results\satellite_only_20230707_initial_run.md
修正目的：　現在のドキュメントは、2023年7月7日の観測日のみの分析結果を記載していますが、現在は2023年7月7日を含む合計3観測日の分析結果が得られているため、ドキュメントの内容を最新の分析結果に更新する必要があります。

1. ファイル名を satelite_only_20230707_initial_run.md から satellite_only_analysis_results.md に変更する。
2. 研究の結果を、20230707の観測日のみの分析結果から、20230707の観測日を含む合計3観測日の分析結果に更新する。分析結果はdata\csv\analysis配下にある各種ファイルを参照してまとめること。また、分析結果は、docs\03_results\GIS_IDEAS_abstract.mdの内容が非常に参考になる。

- docs\02_methods\analysis_workflow.md
修正目的：　GISデータに関する内容について、測量由来GISデータに関する記述しかないが、研究のシナリオは、Satellite Only / Limited / Full の3段階で進めることが決まっている。オープンソースGISデータに関する内容も追加する必要がある。docs\01_planning\available_gis_data.mdには、オープンソースGISデータの利用を検討した結果が記載されているため、これを参考にして、オープンソースGISデータに関する内容を追加すること。また、都市構造パラメータの算出に関して、測量由来GISデータを使用する前提の記載になっているので、これは修正し、どのGISデータを使用する場合でも対応できるような内容に修正すること。

修正項目：
  - docs\01_planning\available_gis_data.mdに記載されているオープンソースGISデータに関する内容を、docs\02_methods\analysis_workflow.mdのGISデータに関する内容に追加すること。

  - 実装スケジュール　や　 5.3.1 現時点の実行順序　、未確定事項・今後の検討課題　を、現在の研究の進捗に合わせて最新の内容に更新すること。

  - Step 3: 都市構造パラメータ算出 におけるGIS由来指標の表における、データソースの内容を、測量由来GISデータを使用する前提の内容から、どのGISデータを使用する場合でも対応できるような内容に修正すること。
  - 確定していない分析、算出方法については、確定していないことを明記する

- docs\03_results\data_preparation_status.md
修正目的：　このドキュメントは、測量由来GISデータの整理・加工・調査の進捗状況を記載するドキュメントだが、ファイル名からは測量由来GISデータに関する内容を記載するドキュメントであることがわからないため、ファイル名を data_preparation_status.md から survey_gis_data_preparation_status.md に変更すること。また、ドキュメントの内容も、測量由来GISデータの整理・加工・調査の進捗状況を記載する内容に修正すること。

- docs\02_methods\calc_urban_params_guide.md
修正目的： 入力データが測量由来GISデータのmerge_XX.gpkgの内容を前提とした内容になっているが、研究のシナリオは、Satellite Only / Limited / Full の3段階で進めることが決まっているため、どのGISデータを使用する場合でも対応できるような内容に修正すること。また、ドキュメントの内容も、現在の研究の進捗に合わせて最新の内容に修正すること。

## 要件
- ドキュメント内容は、全体の構成を大きく変えてしまうとgitの差分を追いにくくなってしまうため、基本的には現在のドキュメントの構成を維持したまま、内容を更新すること。
- 不用意に記述を削除してしまうと、過去の分析内容や研究の進捗がわからなくなってしまうため、削除する記述は最小限にとどめること。
- README.mdなど他ドキュメントの内容と矛盾しないようにすること。
- data_preparation_status.md の変更に伴い、関連するドキュメントの内容も必要に応じて修正すること。


## 参考
- docs\03_results\satellite_only_20230707_initial_run.md
- docs\02_methods\analysis_workflow.md
- docs\03_results\data_preparation_status.md
- docs\02_methods\calc_urban_params_guide.md



---

共通ルールは以下のファイルを参照すること
.github\copilot-instructions.md
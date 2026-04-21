---
agent: agent
---

# タスク: 学会用のアブストラクトの完成

## 概要
国際学会用の研究アブストラクトを改善し、提出用文章に完成させるタスクです。
アブストラクトは、研究の目的、方法、結果、結論を簡潔にまとめたものであり、A4用紙4枚程度の分量（図表や参考文献、keywordsを含む）で作成する必要があります。


## タスク詳細
create_abstract.prompt.md のタスクでは、下書きとして、各節に記述する文章と、記載する図表のアイデアを、mdファイルにまとめることをメインタスクとしていました。
本タスクでは、下書きをもとに、文章のブラッシュアップ、構成の見直しなど改善を行い、提出用のアブストラクトを完成させることをメインタスクとします。
docs\03_results\conference_abstract_rq3_satellite_only_draft.md　を提出用のアブストラクトとして完成させることを目指します。

修正はチェックリストを用いて行います。

未修正：☐ 
修正済み：✅

## 修正前に行うか検討していること
✅　複数の観測日時で分析を行うかどうか
現状、下書きの段階では、単一の観測日時でしか分析を行っていませんが、提出用のアブストラクトでは、複数の観測日時で分析を行うことを検討しています。アブストラクト提出までに時間の余裕があるため、複数の観測日時で分析を行い、分析結果をアブストラクトに反映させることができれば、より説得力のあるアブストラクトになると考えています。
複数の観測日時で分析したほうが良いか意見をもらいたいです。


✅　複数日時の分析を遂行し、各節を更新する
2023年と2024年に観測された衛星データのうち、雲マスクや、ROIのカバー率を考慮して、２つの日時の追加データを確保した。
探索結果は以下のファイルに記載されている。
- data\output\gee_search_satellite_data_results.csv

追加データは以下のディレクトリに保存している。
- data\output\indices\2023
- data\output\LST\2023

追加データについても、同様の分析を行い、結果をアブストラクトに反映させることを検討している。

タスク要件：
- 追加データで分析を行う
- アブストラクトに反映するか、検討する
- アブストラクトに反映するならば、アブストラクトの各節を更新する

実施内容メモ：
- `2023-07-23T03:23:09`
- `2024-11-30T03:23:36`
- 集計結果出力: `data/csv/analysis/satellite_only_multidate_summary.csv`





## 改善項目


### 全体として
✅　用語の使用に関して  
Satelite Only, Limite, Fullシナリオなど、私が勝手に定義したものを使用しているが、これらの用語は一般的に使用されているものではないため、これらの用語は用いない。
都市構造パラメータに関しては、どういった定義なのかを説明したうえで、都市構造パラメータという用語を使用することは問題ないと考えている。

✅　アブストラクト中に含まれるRQの表現
RQというのは、私の研究計画書における内容であり、本アブストラクトにRQという表現をそのまま使用するのは適切ではないと考えている。RQという表現を使用せずに、研究の目的や、分析の内容を説明する表現に修正する必要がある。

✅　参考文献の引用箇所を明確にする
現状、参考文献の引用箇所が明確になっていないため、どの文がどの文献を引用しているか明記しておく（wordで提出用アブストラクトを作成する際に確認しやすい）
参考文献のドキュメントは、充実しているのでそれらを参照すれば適切に引用できると考えている。
特にIntroductionは、先行研究を適切に引用し、本研究の違いや位置づけを明確に記述すること。

✅　本文中に図表の内容を説明する文章を入れる
図表をアブストラクトに入れる場合、挿入する図表は、本文中でも説明する必要がある。図表を挿入するだけでは、読者にとってわかりにくい可能性があるため、図表の内容を説明する文章を入れることが望ましい。
図-1以外では、図表の内容を説明する文章が入っていないため、図表の内容を説明する文章を入れる必要がある。
例：
日本語: 研究対象領域（ROI）は、図-1に示すベトナム・ハノイ市である。  
English: The research area of ​​interest (ROI) is Hanoi, Vietnam, as shown in Figure 1.


例：（他文献の例）
The temperature trends in Da Nang City, as presented in Table 2 and Figure 4, reveal a significant increase in average temperatures over the study period.

Figure 6 indicates that built-up and bare land consistently exhibit the highest temperatures compared to water bodies and vegetated areas.

✅　図のタイトルについて（matplotlibで作成した図のタイトルを変更し、出力する）
どの観測日時の結果なのかわからない問題や、Satelite Onlyという、論文中で使用しない用語がタイトルに入っている問題があるため、matplotlibで作成した図のタイトルを変更し、出力することを検討している。
- モデル性能比較図
旧； Satellite Only Model Performance Comparison
新： Model Performance Comparison {観測日時}
- 特徴量重要度図
旧； Satellite Only Feature Importance
新； Feature Importance {観測日時}
- SHAP値の分布図
旧； SHAP value (impact on model output) 
新； SHAP value distribution {観測日時}

### Abstract
✅　提出用ルールに沿った構成にする
ルール：
要約は、読者に論文の簡単な概要を示すものでなければなりません。論文の内容を簡潔に説明し、重要な用語を含める必要があります。有益で分かりやすく、論文の全体的な範囲を示すだけでなく、得られた主な結果と導き出された結論も述べる必要があります。要約はそれ自体で完結している必要があり、定義されていない略語を含めたり、表番号、図番号、参考文献、数式を参照したりしてはなりません。抄録サービスに直接掲載できるものでなければならず、通常は300語を超えないようにしてください。


### Methodology
✅　LST算出ロジックをわかりやすく説明する
現状の文の課題： 「SMW 法を採用した。」とあるが、SMW法が何であるかわからない
修正方針：以下をベースに修正する。
~~~ 
Ermida et al. (2020; Ref. 1) の手法を用いて算出した。算出フローは以下のとおりである。

(
算出ロジックをわかりやすく説明するために、算出フローを箇条書きで記載する
)

~~~
例： 算出フロー例：あっているかわからないので要確認
- Calculation of TOA (Top of Atmosphere) spectral radiation: Deriving the TOA radiance from the satellite sensor data using radiometric correction formulas.
- Convert radiation value to temperature value: Transforming TOA radiance into brightness temperature using the Planck function.
- Calculate NDVI value: Computing the NDVI to assess vegetation cover.
- Calculate the percentage of vegetation (Pv): Deriving the fraction of vegetation cover based on NDVI values.
- Calculate emission (ε) value: Determining surface emissivity using NDVI-based methods.
- Calculate the surface temperature: Applying the radiative transfer equation to estimate LST.

✅ データの採用理由を明確に
現状： 「探索結果から、品質とカバー率を考慮して」
課題：　どんな探索方法をしたのかわかりにくい
修正方針：　もっと具体的に書く（マスクの内容、カバー率の基準なども書く）

✅ 研究対象領域の説明文を一文いれる
Methodologyのどこかに、研究対象領域の説明文を一文いれる。
一文でいいのは、図でROIの位置を示すため、文章での説明は簡潔にするため。

✅　初期段階、ベースラインといった、研究の進捗や、分析の内容を表す表現の使用に関する懸念
学会発表用の梗概では、研究の進捗管理を示す語よりも、今回示す分析範囲と結果の意味が伝わる表現を優先する。
「初期分析」「ベースライン」「第一段階」などは必要最小限にとどめ、「今回の結果」「参照結果」「他条件との比較に向けた結果」などの表現へ置き換える方向で修正する。


### Results

✅ 文章のブラッシュアップ
 Resultsの内容は、分析結果をわかりやすく説明することが重要である。現状の内容はやや簡略すぎるため、分析結果の内容をわかりやすくなるように、ブラッシュアップが必要である。分析結果を確認し、事実に基づいて、分析結果の内容をわかりやすく説明する文章に修正する必要がある。

✅　LSTの算出結果は、平均値の記載だけでいいのか？
LSTの算出結果は、平均値だけでなく、分布や、他の条件との比較なども記載することが望ましい。平均値だけでは、分析結果の内容を十分に説明できない可能性があるため、分布や、他の条件との比較なども記載することを検討する必要がある。

## 関連ファイル
- docs\01_planning\research_guide.md
研究計画書
- docs\02_methods\analysis_workflow.md
分析フロー


---

共通ルールは以下のファイルを参照すること
.github\copilot-instructions.md

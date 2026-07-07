---
name: create-progress-report
description: "個別ゼミ向け進捗報告パワポを自動生成する。GitHub Projectの完了日とgit commit履歴から過去3週間の進捗を収集し、対話的に構成を決めてQGIS画像生成・pptx作成まで一体実行する。「ゼミ資料を作って」「進捗報告パワポ」「progress report」などのリクエストで使用する。"
---

# 個別ゼミ進捗報告パワポ生成スキル

月2回の個別ゼミ（指導教員向け）の進捗報告資料を、GitHub Issues / git 履歴から半自動生成する。

レイアウト型・カラーパレット・QGIS画像生成の詳細は [reference.md](reference.md) を参照。

## 実行手順

以下のチェックリストをコピーして進捗を追跡する:

```text
- [ ] Step 1: 進捗候補の収集（過去3週間）
- [ ] Step 2: 報告する進捗の選択
- [ ] Step 3: ページ数確認・スライド構成案の提案
- [ ] Step 4: 「今後の予定」の選択
- [ ] Step 5: ファクトチェック
- [ ] Step 6: 画像生成（QGIS-MCP）
- [ ] Step 7: スライド生成（/pptx）・調整
- [ ] Step 8: 保存・報告履歴ログの更新
```

### Step 1: 進捗候補の収集（過去3週間）

収集期間は**固定で過去3週間**とする（ゼミ開催日からの逆算はしない）。

1. **Project 全アイテムの収集（主情報源）**: GitHub Project の全アイテム（Status・完了日・ラベル）を**ページネーションで最後まで**取得する

   ```bash
   gh api graphql -f query='query($cursor: String) { user(login:"HitsujiNeko") { projectV2(number:1) { items(first:100, after:$cursor) { nodes { content { ... on Issue { number title labels(first:10){ nodes { name } } } } fieldValues(first:20) { nodes { ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } } ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } } } } } pageInfo { hasNextPage endCursor } } } } }' -F cursor="$CURSOR"
   ```

   - 初回は `-F cursor` を省略（または空）で実行し、`pageInfo.hasNextPage` が `true` の間は `endCursor` を `cursor` に渡して繰り返し、全ページを結合する（`items(first:100)` 単発ではアイテムが100件を超えると取りこぼす）
   - 結果から「完了日」フィールドが過去3週間以内の Issue（番号・タイトル・ラベル）を抽出する
   - フィールド名の注意: Status フィールドは英語名 `Status`、「開始日」「完了日」「優先度」は日本語名
   - 注意: `gh project item-list` は日本語フィールド名の先頭文字を破壊する（先頭文字を小文字化する際にマルチバイト文字を壊す）ため使用しない。日本語を含むJSONをパイプで直接処理すると文字化けするため、一時ファイルに書き出してから UTF-8 指定で読む
   - 取得結果は Step 4（今後の予定）でも使うため保持しておく

2. **commit 履歴の収集（作業内容の補足）**:

   ```bash
   git log --since="3 weeks ago" --date=short --pretty=format:"%h %ad %s" main
   ```

3. **報告履歴ログとの突き合わせ**: `.github/progress_report_history.json` を読み、前回までに報告済みの Issue 番号を確認する

### Step 2: 報告する進捗の選択

進捗候補をラベルで分類し、AskUserQuestion（複数選択可）で提示する。

- **報告候補**: `analysis` `data-prep` `docs` `workflow` ラベルの Issue
- **除外候補**（一覧には残し、選択可能にする）: `bug` `refactoring` ラベルの Issue、および報告履歴ログで既報告の Issue

各候補には「Issue番号・タイトル・完了日・関連commitの要約」を添える。

### Step 3: ページ数確認・スライド構成案の提案

1. 「全何ページのスライドにするか」をユーザーに確認する（目安: 表紙1 + 進捗1件あたり1-2枚 + 今後の予定1枚）
2. 選択された進捗とページ数をもとに、**各ページの概要（タイトル・レイアウト型・掲載内容・使用図表）** を一覧で提案する
3. レイアウト型は [reference.md](reference.md) の型（カード型 / stat型 / 比較型 / 図表中心型 / リスト型）から内容に応じて選択する
4. ユーザーの修正指示を反映して構成を確定する

### Step 4: 「今後の予定」の選択

Step 1 で取得済みの Project アイテムから、**Status が「未着手」または「進行中」** の Issue を抽出し、掲載するものをユーザーに選択してもらう（AskUserQuestion・複数選択可）。

- `gh issue list --state open` は使わない（Project 外の open Issue が混ざり、未着手/進行中のステータス判定もできないため）
- 各候補には「Issue番号・タイトル・Status・優先度」を添える

### Step 5: ファクトチェック

スライド構成案に含まれる**数値・固有名詞（件数、データサイズ、精度指標、データセット名、期間等）** を「記載値 / 出典（Issue番号・出力ファイルパス）」の一覧表で提示し、生成前にユーザーの確認を得る。

- 精度指標等の数値は Issue 本文や会話の記憶ではなく、`data/csv/analysis/` 等の出力ファイルから読み取って転記する
- 出典が確認できない値は「要確認」と明示し、スライドには含めない

### Step 6: 画像生成（QGIS-MCP）

1. 選択された進捗の内容から、表示すべき地図画像（レイヤー・範囲・テーマ）を推測して提案する（リポジトリ内に既存の出力画像はほぼ無いため、都度生成を基本とする）
2. ユーザーの承認・修正を得てから QGIS-MCP で生成する
3. 生成手順・注意事項（`render_map` の制約、`save_project` 禁止、状態復元）は [reference.md](reference.md) の「QGIS画像生成ガイド」に**必ず従う**
4. 生成画像は `presentations/assets/` に保存する（Git管理外）

QGIS-MCP が利用できない場合は、既存PNG（`data/csv/analysis/*.png` 等）の利用をユーザーに提案する。

### Step 7: スライド生成（/pptx）・調整

1. `/pptx` スキルを使用してスライドを生成する
2. カラーパレットは **Midnight Executive で固定**: Primary `#1E2761` / Secondary `#CADCFC` / Accent `#FFFFFF`
3. スライドレベルは「個別ゼミ＝指導教員向け」固定プロファイル: 専門用語使用可、結論ファースト、簡潔な箇条書き、図表中心
4. 生成後、各スライドのプレビュー確認をユーザーに依頼し、対話しながらレイアウト・内容を調整する

### Step 8: 保存・報告履歴ログの更新

1. 完成 pptx を `presentations/progress_report_YYYYMMDD.pptx` として保存する（フォルダが無ければ作成する。Git管理外）
2. `.github/progress_report_history.json` に今回の報告を追記する（date / file / reported_issues / notes）
3. 履歴ログの変更をユーザーに提示し、承認後にコミットする
   - コミットメッセージ: `docs: 個別ゼミ進捗報告（YYYY-MM-DD）の履歴を記録 (#{Issue番号})`（対応 Issue がない場合は番号を省略）

## 注意事項

- pptx はバイナリのため Git 管理しない（`presentations/` は `.gitignore` 対象）
- Issue に記載のない成果を推測でスライドに書かない。会話で補足された内容は出典を「ユーザー提供」として扱う
- QGIS 操作ではユーザーの作業中プロジェクトの状態を汚さない（詳細は reference.md）

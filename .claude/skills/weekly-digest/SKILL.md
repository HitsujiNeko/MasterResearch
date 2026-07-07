---
name: weekly-digest
description: "過去1週間の研究進捗（完了Issue・新規着手・進行中・主要commit）を集計し、専用Issue「研究進捗 週次ダイジェスト」にコメントとして追記する。「週次ダイジェスト」「今週の進捗をまとめて」「weekly digest」などのリクエストで使用する。"
---

# 週次進捗ダイジェストスキル

GitHub Project と git 履歴から過去7日間の進捗を集計し、専用Issueに時系列で蓄積する。
ゼミ資料作成（`/create-progress-report`）の素材・停滞Issueの検知にも使う。

## 実行手順

### Step 1: 進捗データの収集

1. **Project 全アイテムの取得**（GraphQL。`gh project item-list` は日本語フィールド名を破壊するため使用禁止）。**ページネーションで最後まで**取得する:

   ```bash
   gh api graphql -f query='query($cursor: String) { user(login:"HitsujiNeko") { projectV2(number:1) { items(first:100, after:$cursor) { nodes { content { ... on Issue { number title state labels(first:10){ nodes { name } } } } fieldValues(first:20) { nodes { ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } } ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } } } } } pageInfo { hasNextPage endCursor } } } } }' -F cursor="$CURSOR"
   ```

   - 初回は `-F cursor` を省略（または空）で実行し、`pageInfo.hasNextPage` が `true` の間は `endCursor` を `cursor` に渡して繰り返し、全ページを結合する（`items(first:100)` 単発ではアイテムが100件を超えると取りこぼす）
   - 日本語を含むJSONはパイプで直接処理せず、一時ファイルに書き出してから UTF-8 指定の python で読む（`PYTHONIOENCODING=utf-8` 併用）

2. **分類**（基準日 = 実行日）:
   - **完了**: 「完了日」が過去7日以内
   - **新規着手**: 「開始日」が過去7日以内（完了済みを除く）
   - **進行中・保留**: 現在のステータスが「進行中」「保留」
   - **長期滞留**: 「進行中」のまま開始日から21日以上経過したもの（注意喚起用）

   フィールド名の注意: ステータスのフィールド名は **`Status`（英語）**、値（未着手/進行中/保留/完了/キャンセル）と「開始日」「完了日」「優先度」フィールド名は日本語（実データで確認済み）

3. **commit 履歴**:

   ```bash
   git log --since="7 days ago" --date=short --pretty=format:"%h %ad %s" main
   ```

### Step 2: ダイジェストの生成

以下の構成でMarkdownを生成する。事実（Issue・commitの記録）のみで構成し、推測による進捗評価は書かない。

```markdown
## 週次ダイジェスト（YYYY-MM-DD 〜 YYYY-MM-DD）

### ✅ 完了（{n}件）
- #番号 タイトル（ラベル / 完了日）

### 🚀 新規着手（{n}件）
- #番号 タイトル（ラベル / 開始日）

### 🔄 進行中・保留（{n}件）
- #番号 タイトル（ステータス / 開始日）

### ⚠️ 長期滞留（21日以上「進行中」）
- #番号 タイトル（開始日: YYYY-MM-DD）※該当なしの場合はセクションごと省略

### 📝 主な commit（{n}件）
- ハッシュ 日付 メッセージ（多い場合は代表10件に絞り、件数を明記）

---
🤖 このコメントは /weekly-digest スキルにより作成されました。
```

### Step 3: 専用Issueへの投稿

1. 専用Issueを検索する:

   ```bash
   gh issue list --state open --search "研究進捗 週次ダイジェスト in:title" --json number,title
   ```

2. **存在しない場合（初回のみ）**: タイトル「研究進捗 週次ダイジェスト」・ラベル `workflow` でIssueを作成する。本文には「このIssueは週次ダイジェストの蓄積専用。/weekly-digest スキルがコメントを追記する」と記載する。プロジェクトへの追加・優先度設定は行わない
3. ダイジェストを一時ファイルに書き出し、`gh issue comment {番号} --body-file {一時ファイル}` で投稿する（日本語文字化け対策のためBashツールを使用）
4. 投稿したコメントのURLをユーザーに報告する

## 注意事項

- 同一週に複数回実行した場合は上書きせず、新しいコメントとして追記する（実行日を明記しているため履歴として共存可能）
- リポジトリへのコミットは発生しない（Issueコメントのみ）
- 集計対象は Project 登録済みIssueのみ。Project未登録のIssueが疑われる場合はその旨を注記する

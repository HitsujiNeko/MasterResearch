# GitHub Project / gh CLI 共通リファレンス

**役割**: 複数スキル（weekly-digest / create-progress-report / issue-create 等）が共有する GitHub Project の取得クエリと日本語処理の注意事項の**唯一の正本**。クエリ・フィールド名を変更する場合は本ファイルのみを更新する。

---

## Project 全アイテムの取得（GraphQL・ページネーション必須）

```bash
gh api graphql -f query='query($cursor: String) { user(login:"HitsujiNeko") { projectV2(number:1) { items(first:100, after:$cursor) { nodes { content { ... on Issue { number title state labels(first:10){ nodes { name } } } } fieldValues(first:20) { nodes { ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } } ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } } } } } pageInfo { hasNextPage endCursor } } } } }' -F cursor="$CURSOR"
```

- **初回は `-F cursor` 自体を付けずに実行する**（空文字を渡すと `after: ""` となり無効な cursor になる）
- `pageInfo.hasNextPage` が `true` の間は `endCursor` を `cursor` に渡して繰り返し、**全ページを結合する**（`items(first:100)` 単発ではアイテムが100件を超えると取りこぼす）

## フィールド名の注意（実データで確認済み）

- ステータスのフィールド名は **`Status`（英語）**
- ステータスの値（未着手/進行中/保留/完了/キャンセル）と「開始日」「完了日」「優先度」のフィールド名は**日本語**
- ステータス・優先度の設定に使う各種 ID 一覧は [../issue-create/reference.md](../issue-create/reference.md) を参照

## 使用禁止コマンド

- **`gh project item-list` は使用しない**: 日本語フィールド名の先頭文字を破壊する（先頭文字を小文字化する際にマルチバイト文字を壊す）
- **`gh issue list --state open` を Project 集計の代用にしない**: Project 外の open Issue が混ざり、ステータス判定もできない

## 日本語テキストの安全な処理

- **日本語を含む JSON はパイプで直接処理しない**: 一時ファイルに書き出してから UTF-8 指定の python で読む（`PYTHONIOENCODING=utf-8` 併用）
- **日本語本文の Issue / コメント投稿**: 本文を Bash ツールで一時ファイルに書き出し、`--body-file {一時ファイル}` で渡す（直接 `--body` に渡すと文字化けする）

  ```bash
  gh issue create --title "..." --label "..." --body-file {一時ファイル}
  gh issue comment {番号} --body-file {一時ファイル}
  ```

## 認証エラー時

`gh auth refresh -s project` の実行をユーザーに案内し、設定未完了を明示的に警告する。暗黙にスキップしない。

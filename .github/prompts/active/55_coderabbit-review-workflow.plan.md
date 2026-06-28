# #55 CodeRabbit指摘対応フローの厳格化 — 実装計画書

## アプローチ

`task-workflow.md` の「④ CodeRabbit 自動レビューの確認・対応」セクション（L200-208）を改訂する。1コミットで完結する変更。

### 改訂内容

**課題①: 確認タイミング・方法の明確化**

PR作成直後にCodeRabbitのレビュー到着を確認するコマンドを明記する。

```powershell
# CodeRabbitのレビュー到着確認
gh pr view {PR番号} --json reviews --jq '.reviews[] | select(.author.login == "coderabbitai")'

# 個別のレビューコメント取得
gh api repos/{owner}/{repo}/pulls/{PR番号}/comments
```

CodeRabbitのレビューは通常PR作成から数分で届く。未到着の場合はユーザーに状況を報告し、待機するか先に進むかを確認する。

**課題②: コメント返信の必須化**

指摘への対応後、該当コメントに `gh api` で返信することを必須手順に追加する。

```powershell
# レビューコメントへの返信
gh api repos/{owner}/{repo}/pulls/{PR番号}/comments/{comment_id}/replies -f body="対応しました: {コミットハッシュ短縮形}"
```

返信フォーマット: `対応しました: {コミットハッシュ短縮形}`

**課題③: 指摘単位のコミット分割**

- 原則: 1指摘1コミット
- 例外: 同一パターンの指摘が複数箇所 → まとめて1コミット可
- コミットメッセージ形式: `fix: {対応内容の要約} (#{Issue番号})`

### 役割分担テーブルの更新

L248 の Claude 側の記述を以下に更新する:

- 現在: `レビューコメント確認・分類・修正提案 | 対応要否を判断`
- 更新後: `レビュー到着確認・指摘分類・対応実装・コメント返信 | 対応要否を判断`

### CLAUDE.md について

CLAUDE.mdにはCodeRabbitの直接的な記述はなく、`@.github/task-workflow.md` で参照している。task-workflow.md の改訂で十分であり、CLAUDE.md の更新は不要。

## 成果物一覧

| ファイル | 操作 |
|---|---|
| `.github/task-workflow.md` | 更新（④セクション改訂 + 役割分担テーブル更新） |

## 動作確認手順

- 改訂後の④セクションに具体的なコマンド例が含まれていること
- 段階的コミット原則との整合性が取れていること
- 役割分担テーブルが改訂内容と一致していること
- markdownlint でエラーがないこと

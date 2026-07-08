---
description: CodeRabbit 自動レビューの確認・分類・対応・返信サイクルを実行する
argument-hint: "{PR番号}"
---

# CodeRabbit レビュー対応: PR #$ARGUMENTS

PR 作成後、CodeRabbit が自動でレビューコメントを付ける（`.coderabbit.yaml` の `auto_review.enabled: true`）。

> CodeRabbit のレビューは補助的なものであり、指摘への対応要否はユーザーが判断する。

## Step 1: レビュー到着の確認

```bash
# CodeRabbit のレビュー到着確認
gh pr view $ARGUMENTS --json reviews --jq '.reviews[] | select(.author.login == "coderabbitai")'

# 個別のレビューコメント取得
gh api repos/{owner}/{repo}/pulls/$ARGUMENTS/comments
```

- レビュー未到着の場合はユーザーに状況を報告し、到着まで待機する
- 指摘なしで承認された場合はその旨を報告して終了する

## Step 2: 指摘の分類・提示

レビューコメントを以下に分類してユーザーに提示し、対応要否の判断を仰ぐ。

- **対応推奨**: コードの正確性・一貫性に関わる指摘
- **任意**: スタイルや好みに関する提案

## Step 3: 指摘ごとの対応サイクル

ユーザーが対応を承認した指摘について、以下を繰り返す。

```text
実装 → コミット → push → コメント返信 → 次の指摘へ
```

- **原則 1指摘1コミット**。同一パターンの指摘が複数箇所に出た場合はまとめて1コミットで対応可
- コミットメッセージ: `fix: {対応内容の要約} (#{Issue番号})`

## Step 4: コメントへの返信

- **対応した指摘**: 個別に返信する

  ```bash
  gh api repos/{owner}/{repo}/pulls/$ARGUMENTS/comments/{comment_id}/replies -f body="対応しました: {コミットハッシュ短縮形}"
  ```

- **見送った指摘**: 個別返信は不要。PR に通常コメントを1件投稿し、見送った指摘と理由を一括で記載する（例: 「以下の指摘はユーザー判断により対応不要としました: …」）

## Step 5: 完了報告

対応した指摘数・見送った指摘数・push したコミットをユーザーに報告し、squash merge の実施（ユーザーの専権）を案内する。

---
description: CodeRabbit レビューの起動状態の確認（区分 R は承認を得て手動起動）・分類・対応・返信サイクルを実行する
argument-hint: "{PR番号}"
---

# CodeRabbit レビュー対応: PR #$ARGUMENTS

本リポジトリでは CodeRabbit が自動レビューせず、PR 作成時には「Trigger review」チェックボックスつきのスキップ通知だけを残す。そのため本コマンドは、**区分 R の PR** で未起動であれば手動起動してから、レビューへの対応に進む。理由・対象の区分・再レビューの扱いは [task-workflow.md](../../.github/task-workflow.md) の「5. タスク完了 ④」を正本とする。

> CodeRabbit のレビューは補助的なものであり、指摘への対応要否はユーザーが判断する。

## Step 1: 起動状態の確認と手動起動

```bash
# CodeRabbit のレビュー（指摘の本体）
gh pr view $ARGUMENTS --json reviews --jq '.reviews[] | select(.author.login == "coderabbitai")'

# PR の最新コミット（レビューの commit.oid と比べ、未レビューのコミットの有無を見る）
gh pr view $ARGUMENTS --json headRefOid --jq '.headRefOid'

# 通常コメント（スキップ通知・起動の投稿・CodeRabbit の応答）。本文は先頭に HTML コメントの目印が並び、
# 切り詰めると判定の手がかりが見えなくなるため、目印の有無を真偽値で出す
# （Windows の Git Bash ではバックスラッシュが崩れるため、正規表現ではなく contains で判定する）
# スキップ通知には「Trigger review」以外のチェックボックス（Autofix 等）も並ぶため、その行だけを見る
gh pr view $ARGUMENTS --json comments --jq '.comments[] | {author: .author.login, createdAt, edited: .includesCreatedEdit,
  skip_notice: (.body | contains("skip review by coderabbit.ai") or contains("fewer than 10 stars")),
  trigger_checked: (.body | split("\n") | any(contains("Trigger review") and contains("[x]"))),
  trigger_comment: (.body | contains("@coderabbitai review")),
  rate_limit_or_error: (.author.login == "coderabbitai" and (.body | ascii_downcase | contains("rate limit") or contains("error")))}'

# 変更区分（PR 本文の「変更区分」欄）
gh pr view $ARGUMENTS --json body --jq '.body'

# 個別のレビューコメント取得
gh api repos/{owner}/{repo}/pulls/$ARGUMENTS/comments
```

取得結果から起動状態を判定する。

| 状態 | 判定の目安 | 対応 |
|---|---|---|
| 到着済み | `coderabbitai` のレビューがあり、最新のレビューの `submittedAt` が最新の起動の投稿（`trigger_comment` が真のコメント）の `createdAt` より後である（起動の投稿がなければ、レビューがあるだけでよい） | Step 2 へ（指摘対応後の再実行では、Step 4 で返信済みの指摘を除いて扱う。レビューの `commit.oid` が `headRefOid` と異なる場合は、以降のコミットが未レビューであることを報告に添える） |
| 未起動 | `coderabbitai` のレビューがなく、起動の操作（`trigger_comment` が真のコメント、またはスキップ通知の `trigger_checked` が真）もない。スキップ通知（`skip_notice` が真）の有無は問わない（PR 作成直後で通知がまだ付いていない場合を含む） | 下記の手動起動 |
| 起動済み・未到着 | 起動の操作はあるが、その後の `coderabbitai` のレビューがまだない（再起動の前からある古いレビューは数えない） | 下記の待機 |

- チェックボックスは起動後に未チェックへ戻ることがあり（未確認）、`trigger_checked` だけでは起動済みを見分けられない場合がある。そのため手動起動の確認では、ユーザーがすでにチェックボックスを押していないかも併せて尋ねる
- **手動起動**（未起動の場合）:
  - **区分 R**: 投稿の前に「PR #{PR番号} に `@coderabbitai review` を投稿してよいか（すでに「Trigger review」を押していないか）」をユーザーに確認し、承認された場合のみ投稿する。外部への書き込みのため、承認は投稿 1 回ごとに取る

    ```bash
    gh pr comment $ARGUMENTS --body "@coderabbitai review"
    ```

  - **区分 S・D**: 起動の対象外である旨を報告し、それでも起動するか（投稿してよいか。すでに「Trigger review」を押していないかも併せて）をユーザーに確認する。承認された場合のみ投稿し、見送られた場合は終了する（本コマンドを実行しただけでは起動を求めたとみなさない）
  - 「変更区分」欄を一意に読み取れない場合は推測で補わず、ユーザーに確認する
- **待機**: レビューの到着には数分かかる。投稿後（または起動済み・未到着の場合）は状況をユーザーに報告し、到着後に上記の確認を再実行する（短い間隔で確認を繰り返さない）
- **レート制限・エラー**: CodeRabbit がレート制限やエラーを通知した場合（`rate_limit_or_error` が真のコメントは本文を確認する）は、内容（待機時間など）をユーザーに報告し、再起動するかどうかの判断を仰ぐ。自動で再投稿しない
- **指摘なしの完了**: 指摘 0 件のときに CodeRabbit がレビューを作るかは未確認である。起動済み・未到着のまま、`coderabbitai` のコメントが編集されている（`edited` が真）または起動後に新たに付いた場合は、その本文を確認し、レビューの完了を示していればその旨を報告して終了する（スキップ通知の目印はレビュー後も本文に残るため、`skip_notice` だけでは判断しない）

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
- 対応の push 後に再レビューは起動しない（起動ごとにレート制限を消費するため。対応内容は squash merge 前の PR レビューで確認する）。ユーザーが求めた場合に限り、Step 1 と同じく承認を得て `@coderabbitai review` を投稿する

## Step 4: コメントへの返信

- **対応した指摘**: 個別に返信する

  ```bash
  gh api repos/{owner}/{repo}/pulls/$ARGUMENTS/comments/{comment_id}/replies -f body="対応しました: {コミットハッシュ短縮形}"
  ```

- **見送った指摘**: 個別返信は不要。PR に通常コメントを1件投稿し、見送った指摘と理由を一括で記載する（例: 「以下の指摘はユーザー判断により対応不要としました: …」）

## Step 5: 完了報告

対応した指摘数・見送った指摘数・push したコミットをユーザーに報告し、squash merge の実施（ユーザーの専権）を案内する。

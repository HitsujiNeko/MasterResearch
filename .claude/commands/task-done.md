---
description: PR マージ後の後処理（main復帰・ブランチ削除・計画書削除・完了記録）
argument-hint: "{Issue番号}（省略時は現在のタスク）"
---

# マージ後処理

ユーザーから「マージしました」の連絡を受けたとき、またはこのコマンドが実行されたときの手順。

## Step 1: 対象 PR の特定とマージ確認

1. 対象 PR を特定する。会話の文脈で PR 番号が明らかな場合はそれを使う。不明な場合は Issue 番号（ブランチ命名規則 `{Issue番号}/{タスク要約英文}`）から引く:

   ```bash
   git branch --list "{Issue番号}/*"                            # ブランチ名の確認
   gh pr list --state all --head {ブランチ名} --json number,url,state
   ```

2. `gh pr view {PR番号} --json state,mergedAt` で対象 PR が **MERGED** であることを確認する。未マージなら中断してユーザーに報告する。

## Step 2: 削除対象の提示（確認ゲート）

以下を列挙してユーザーに提示し、**実行前に1回確認を得る**。

- 削除するローカルブランチ名（および worktree パス。並列実行の場合）
- 削除する計画書ファイル（`.github/prompts/active/` 配下。存在する場合）

## Step 3: 実行

**単一実行の場合:**

```bash
git checkout main
git pull
git branch -D {Issue番号}/{タスク要約英文}
rm .github/prompts/active/{計画書ファイル}   # 存在する場合
```

**並列実行（worktree 隔離）の場合:**

共有ディレクトリは他セッションが使用中の可能性があるため、`git checkout`・`git pull` など**共有ディレクトリのチェックアウト状態を変更するコマンドは一切実行しない**。

```bash
git worktree remove {worktreeパス}
git branch -D {Issue番号}/{タスク要約英文}
```

**共通:**

- Project のステータスを「完了」・完了日（当日）に更新する（GraphQL。ID は `.claude/skills/issue-create/reference.md` を参照）
- Issue 自体は PR の `Closes #{Issue番号}` により自動 close 済みのため、`gh issue close` は不要
- リモートの作業ブランチは「Auto delete head branches」設定により自動削除される（残っている場合は削除をユーザーに案内する。`git push origin --delete` は deny 対象のためユーザーが実行する）

## Step 4: 完了報告

処理結果（削除したブランチ・更新したステータス）をユーザーに報告する。

---
description: PR マージ後の後処理（main復帰・ブランチ削除・計画書削除・完了記録）
argument-hint: "{Issue番号}（省略時は現在のタスク）"
---

# マージ後処理

ユーザーから「マージしました」の連絡を受けたとき、またはこのコマンドが実行されたときの手順。

以降の後処理（ブランチ削除・計画書削除・ステータス更新）は**確認を取らずに一体実行する**。破壊的操作はいずれも Step 1 の MERGED 検証を通過した場合にのみ走るため、実行前の確認は不要とする。計画書ファイル（`.github/prompts/active/` 配下。git 未追跡で不可逆削除）の削除も同様に無確認で行う。

## Step 1: 対象 PR の特定とマージ確認（ハードゲート）

1. 対象 PR を特定する。会話の文脈で PR 番号が明らかな場合はそれを使う。不明な場合は Issue 番号（ブランチ命名規則 `{Issue番号}/{タスク要約英文}`）から引く:

   ```bash
   git branch --list "{Issue番号}/*"                            # ブランチ名の確認
   gh pr list --state all --head {ブランチ名} --json number,url,state
   ```

2. `gh pr view {PR番号} --json state,mergedAt` で対象 PR が **MERGED** であることを確認する。**これは必須のハードゲートである。MERGED でない場合は Step 2 以降を一切実行せず、無条件で中断してユーザーに報告する。**

## Step 2: 実行（無確認）

Step 1 で MERGED を確認したら、以下を確認を取らずに実行する。

**単一実行の場合:**

```bash
git checkout main
git pull
git branch -D {Issue番号}/{タスク要約英文}
rm -f -- .github/prompts/active/{計画書ファイル}   # 存在しなくても成功する
```

**並列実行（worktree 隔離）の場合:**

共有ディレクトリは他セッションが使用中の可能性があるため、`git checkout`・`git pull` など**共有ディレクトリのチェックアウト状態を変更するコマンドは一切実行しない**。

計画書は git 未追跡のため、worktree 内に残っていると `git worktree remove` が未追跡ファイルを理由に停止する。`git worktree remove` の前に計画書を削除する。

```bash
rm -f -- {worktreeパス}/.github/prompts/active/{計画書ファイル}   # 存在しなくても成功する
git worktree remove {worktreeパス}
git branch -D {Issue番号}/{タスク要約英文}
```

**共通:**

- Project のステータスを「完了」・完了日（当日）に更新する（GraphQL。ID は `.claude/skills/issue-create/reference.md` を参照）
- Issue 自体は PR の `Closes #{Issue番号}` により自動 close 済みのため、`gh issue close` は不要
- リモートの作業ブランチは「Auto delete head branches」設定により自動削除される（残っている場合は削除をユーザーに案内する。`git push origin --delete` は deny 対象のためユーザーが実行する）

## Step 3: 完了報告

処理結果（削除したブランチ・更新したステータス）をユーザーに報告する。

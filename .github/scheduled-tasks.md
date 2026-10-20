# 定期実行（スケジュールタスク）の設定と登録手順

> **最終更新**: 2026-10-20
> **関連ドキュメント**: [task-workflow.md](./task-workflow.md)（タスク管理の正本）／[docs/README.md](../docs/README.md)（定期メンテナンス）
> **前提知識**: Claude デスクトップアプリのスケジュールタスク（`scheduled-tasks` MCP）、[スキル運用ルール](../docs/02_methods/skill_operation_rules.md)

Claude デスクトップアプリに登録している定期実行の設定内容と、登録・再登録の手順を記録する。
**設定の実体はリポジトリの外**（`~/.claude/scheduled-tasks/{taskId}/SKILL.md`）にあり Git で追跡されないため、PC の移行や設定の消失に備えて本書に写しを残す。

---

## 1. 登録している定期実行

| taskId | タイトル | スケジュール（cron・現地時刻） | 呼び出すもの | GitHub への書き込み |
|---|---|---|---|---|
| `weekly-docs-consistency-check` | （taskId のまま） | 毎週月曜 9:00（`0 9 * * 1`） | `/check-docs-consistency` | 報告 Issue の起票・差分コメント・close |
| `weekly-digest` | （taskId のまま） | 毎週月曜 9:00（`0 9 * * 1`） | `/weekly-digest` | 「研究進捗 週次ダイジェスト」へのコメント |
| `monthly-external-deps-health-check` | 【毎月】外部依存のヘルスチェック | 毎月1日 9:00（`0 9 1 * *`） | `scripts/check_external_deps.py` | **なし** |
| `monthly-paper-scout` | 【毎月】文献探索（paper-scout） | 毎月1日 9:30（`30 9 1 * *`） | `/paper-scout`（月次自動実行モード） | 「文献候補 月次レポート」の作成（初回のみ）とコメント |

- 実行時刻には、アプリが負荷分散のために数分〜十数分の遅延（jitter）を自動で加える
- **アプリが起動している間だけ実行される**。予定時刻にアプリが閉じていた場合は、次回の起動時に実行される
- 各回は会話の記憶を持たない新しいセッションで始まるため、プロンプトは単体で完結させる。手順の本体はリポジトリ内のスキル・スクリプトに置き、プロンプトはそれを呼び出すだけにする（手順を Git で管理し、プロンプトとの二重管理を避けるため）

## 2. 各タスクのプロンプト

プロンプト中の `{リポジトリのルート}` と `{masterresearch 環境の python.exe}` は、登録する PC の実際のパスに置き換える（PC 固有のため本書には書かない）。

### 2.1 weekly-docs-consistency-check

```text
リポジトリ `{リポジトリのルート}` でドキュメント整合性チェックを**自動実行**として実行する（担当者不在のため、ユーザーへの確認は行わない）。

Skill ツールを使って `check-docs-consistency` スキルを呼び出す。
報告方法（既存の報告 Issue への差分コメント追記／新規起票／全件解消時の close／差分がなければ書き込みなし）は、スキルの「状況別の動作」に従う。スキルの手順以外の書き込みは行わない。
```

### 2.2 weekly-digest

```text
{リポジトリのルート} リポジトリで、研究進捗の週次ダイジェストを作成してください。

手順:
1. 作業ディレクトリを {リポジトリのルート} にする。
2. リポジトリ内の .claude/skills/weekly-digest/SKILL.md を読み、その手順に厳密に従って実行する。GitHub Project の集計クエリ・フィールド名・日本語処理の注意は .claude/skills/shared/github-project-api.md が正本。
3. GitHub Project の読み取りは gh api graphql による直クエリを使う（このマシンには gh CLI がインストール済みで、既存の認証をそのまま使う）。認証エラー（project スコープ不足等）が発生した場合は、代替手段（gh issue list 等）に切り替えず、エラー内容をそのまま報告して終了する。
4. 集計結果は専用Issue「研究進捗 週次ダイジェスト」にコメントとして追記する（存在しなければSKILL.mdの手順どおり新規作成し、プロジェクトへの追加・優先度設定は行わない）。日本語本文は一時ファイルに書き出して --body-file で投稿する。
5. リポジトリへのコミット・pushは行わない。成果物はIssueコメントのみ。
6. 完了したら投稿したコメントのURLを報告する。失敗した場合は、どのステップで何のエラーが出たかを具体的に報告する。
```

### 2.3 monthly-external-deps-health-check

確認項目と判定基準は [check_external_deps.py](../scripts/check_external_deps.py) の冒頭の説明を正本とする（Earthdata トークンの有効期限・GEE の認証状態・OSGeo4W の proj.db・ruff のローカル版と CI 固定版の一致）。問題のある項目（期限切れ・残り45日未満・不一致・判定不能）だけを出力し、終了コードは問題あり=1／問題なし=0。

```text
リポジトリ {リポジトリのルート} で外部依存のヘルスチェックを**自動実行**として実行する（担当者不在のため、ユーザーへの確認は行わない）。

手順:
1. 作業ディレクトリを {リポジトリのルート} にする。
2. PowerShell ツールで次を実行する（conda 環境の python.exe をフルパスで呼ぶ。conda activate は使えない）:
   & "{masterresearch 環境の python.exe}" -m scripts.check_external_deps
3. 終了コード 1 は「要対応の項目あり」を意味し、スクリプトの異常ではない。出力された項目をそのまま報告し、各項目に出力中の対処を1行で添える。終了コード 0 の場合は「問題なし」の1行だけを報告する。
4. 要対応の項目がある場合に限り、PushNotification ツールが使えれば「外部依存: 要対応 N 件（項目名の列挙）」を1行で通知する。問題なしの場合は通知しない。
5. 次の操作は行わない: GitHub（Issue・コメント・PR）への書き込み、リポジトリへのコミット・push、.env やトークンの値の表示・記録、earthengine authenticate などの認証操作（ブラウザが開いて止まるため）。
6. スクリプトを起動できない（ImportError 等）場合は、実行したコマンドと出たエラーを報告して終了する。
```

### 2.4 monthly-paper-scout

手順の本体は [paper-scout スキル](../.claude/skills/paper-scout/SKILL.md)の「月次自動実行モード」を正本とする。提示済みの候補は、報告 Issue の過去コメントに埋め込んだマーカーから [scout_report.py](../src/literature/scout_report.py) が判定して除外する。

```text
リポジトリ {リポジトリのルート} で文献探索を**月次自動実行**として実行する（担当者不在のため、ユーザーへの確認は行わない）。

手順:
1. 作業ディレクトリを {リポジトリのルート} にする。
2. Skill ツールで `paper-scout` スキルを呼び出し、スキルの「月次自動実行モード」の手順に厳密に従う。Python は conda 環境の python.exe（{masterresearch 環境の python.exe}）をフルパスで呼ぶ。出力先はこのセッションのスクラッチパッドとする。
3. 日本語本文は一時ファイルに書き出して --body-file で投稿する。
4. GitHub への書き込みは、スキルの手順にある報告 Issue の作成（初回のみ）とコメント追記だけとする。リポジトリへのコミット・push は行わない。OPENALEX_API_KEY 等の値は表示しない。
5. 完了したら、投稿したコメントの URL（または書き込まなかった理由）を報告する。失敗した場合は、どのステップで何のエラーが出たかを具体的に報告する。
```

## 3. 登録・再登録の手順

登録・変更はリポジトリの外への書き込みにあたるため、**実行前にユーザーの確認を得る**。

1. 既存の登録を確認する: `scheduled-tasks` MCP の `list_scheduled_tasks` で taskId・cron・有効状態を確認する（同じ taskId があれば新規作成せず `update_scheduled_task` で更新する）
2. 新規に登録する: `create_scheduled_task` に次を渡す
   - `taskId`: 1章の taskId
   - `title`: 1章のタイトル（既存2件は未設定）
   - `cronExpression`: 1章の cron（**現地時刻**で解釈される）
   - `description`: 1行の説明
   - `prompt`: 2章のプロンプト（プレースホルダを実際のパスに置き換えたもの）
3. 登録結果を確認する: もう一度 `list_scheduled_tasks` を実行し、`nextRunAt` が想定どおりかを確かめる。すぐに試す場合は `run_scheduled_task` を使う（手動実行と同じ扱い）
4. 本書を更新する: スケジュールやプロンプトを変えたら、本書の1章・2章も同じ内容に直す（本書が写しとして古くならないようにするため）

## 4. 運用上の注意

- `monthly-paper-scout` と `monthly-external-deps-health-check` は、リポジトリの `main` にあるスキル・スクリプトを使う。手順を変えた場合は、変更が `main` に入るまで定期実行には反映されない
- Earthdata トークンの有効期限が切れていなくても、LAADS DAAC からの取得にはプロダクトごとのデータ利用許諾への同意が別に必要である。同意していない場合も「リダイレクト先で 401」となり失効と症状が似るため、ヘルスチェックが OK でも取得に失敗したら同意状況を確認する
- PushNotification がスケジュールタスクの実行セッションで使えるかは**未確認**である。使えない場合でも、実行結果はアプリのスケジュールタスクの実行履歴から確認できる

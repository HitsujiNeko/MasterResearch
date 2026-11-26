# 定期実行（スケジュールタスク）の設定と登録手順

> **最終更新**: 2026-11-26
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
| `weekly-result-staleness-check` | 【毎週】分析結果の陳腐化検出 | 毎週月曜 9:30（`30 9 * * 1`） | `/check-result-staleness` | 報告 Issue の起票・差分コメント・close |
| `monthly-external-deps-health-check` | 【毎月】外部依存のヘルスチェック | 毎月1日 9:00（`0 9 1 * *`） | `scripts/check_external_deps.py` | **なし** |
| `monthly-paper-scout` | 【毎月】文献探索（paper-scout） | 毎月1日 9:30（`30 9 1 * *`） | `/paper-scout`（月次自動実行モード） | 「文献候補 月次レポート」の作成（初回のみ）とコメント |
| `monthly-reproducibility-check` | 【毎月】分析の再現性チェック | 毎月2日 9:00（`0 9 2 * *`） | `scripts/check_reproducibility.py`（`origin/main` の一時的な作業ツリーで実行） | 「分析の再現性チェック 月次レポート」の作成（初回のみ）とコメント |

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

### 2.3 weekly-result-staleness-check

判定の分類と終了コードは [check_result_staleness.py](../scripts/check_result_staleness.py) の冒頭の説明、報告 Issue の特定と書き込みの分岐は [check-result-staleness スキル](../.claude/skills/check-result-staleness/SKILL.md)を正本とする。下記プロンプトの冒頭で `main` 以外なら見送るのに加え、スキル（`main` 以外では書き込まない）とスクリプト（報告モードを `main` 以外では拒否する）も同じ条件で書き込みを止める。既存の週次2件（9:00）と重ならないよう 9:30 に置く（毎月1日が月曜の日は `monthly-paper-scout` と同じ時刻になる）。

```text
リポジトリ {リポジトリのルート} で分析結果の陳腐化検出を**自動実行**として実行する（担当者不在のため、ユーザーへの確認は行わない）。

手順:
1. 作業ディレクトリを {リポジトリのルート} にする。Bash ツールで git branch --show-current を実行し、結果が main でない場合は、何も実行せず「{ブランチ名} がチェックアウトされているため実行を見送った」と報告して終了する（結果が空の場合は {ブランチ名} を「detached HEAD」とする）。main であっても scripts/check_result_staleness.py が存在しない場合は、何も実行せず「main に scripts/check_result_staleness.py が無いため実行を見送った（main が古い可能性がある）」と報告して終了する（いずれもチェックアウトの切り替え・pull はしない）。
2. Skill ツールで `check-result-staleness` スキルを呼び出し、スキルの手順に自動実行として厳密に従う。Python は conda 環境の python.exe（{masterresearch 環境の python.exe}）をフルパスで呼ぶ。一時ファイルの出力先はこのセッションのスクラッチパッドとする。
3. 日本語本文は一時ファイルに書き出して --body-file で投稿する。
4. GitHub への書き込みは、スキルの「状況別の動作」にある報告 Issue の起票・差分コメント・close だけとする。分析の再実行、結果ファイルの変更、リポジトリへのコミット・push は行わない。
5. 完了したら、行った書き込み（Issue・コメントの URL、または書き込まなかった理由）と分類別の件数を報告する。失敗した場合は、どのステップで何のエラーが出たかを具体的に報告する。
```

### 2.4 monthly-external-deps-health-check

確認項目と判定基準は [check_external_deps.py](../scripts/check_external_deps.py) の冒頭の説明を正本とする（Earthdata トークンの有効期限・GEE の認証状態・OSGeo4W の proj.db・ruff のローカル版と CI 固定版の一致）。問題のある項目（期限切れ・残り45日未満・不一致・判定不能）だけを出力し、終了コードは問題あり=1／問題なし=0。

```text
リポジトリ {リポジトリのルート} で外部依存のヘルスチェックを**自動実行**として実行する（担当者不在のため、ユーザーへの確認は行わない）。

手順:
1. 作業ディレクトリを {リポジトリのルート} にする。Bash ツールで git branch --show-current を実行し、結果が main でない場合は、何も実行せず「{ブランチ名} がチェックアウトされているため実行を見送った」と報告して終了する（結果が空の場合は {ブランチ名} を「detached HEAD」とする）。main であっても scripts/check_external_deps.py が存在しない場合は、何も実行せず「main に scripts/check_external_deps.py が無いため実行を見送った（main が古い可能性がある）」と報告して終了する（いずれもチェックアウトの切り替え・pull はしない）。
2. PowerShell ツールで次を実行する（conda 環境の python.exe をフルパスで呼ぶ。conda activate は使えない）:
   & "{masterresearch 環境の python.exe}" -m scripts.check_external_deps
3. 終了コード 1 は「要対応の項目あり」を意味し、スクリプトが起動できなかったという意味ではない（1項目の判定中に予期しない例外が出た場合も、その項目が UNKNOWN として報告される）。出力された項目をそのまま報告し、各項目に出力中の対処を1行で添える。終了コード 0 の場合は「問題なし」の1行だけを報告する。
4. 要対応の項目がある場合に限り、PushNotification ツールが使えれば「外部依存: 要対応 N 件（項目名の列挙）」を1行で通知する。問題なしの場合は通知しない。
5. 次の操作は行わない: GitHub（Issue・コメント・PR）への書き込み、リポジトリへのコミット・push、.env やトークンの値の表示・記録、earthengine authenticate などの認証操作（ブラウザが開いて止まるため）。
6. スクリプトを起動できない（ImportError 等）場合は、実行したコマンドと出たエラーを報告して終了する。
```

### 2.5 monthly-paper-scout

手順の本体は [paper-scout スキル](../.claude/skills/paper-scout/SKILL.md)の「月次自動実行モード」を正本とする。提示済みの候補は、報告 Issue の過去コメントに埋め込んだマーカーから [scout_report.py](../src/literature/scout_report.py) が判定して除外する。

```text
リポジトリ {リポジトリのルート} で文献探索を**月次自動実行**として実行する（担当者不在のため、ユーザーへの確認は行わない）。

手順:
1. 作業ディレクトリを {リポジトリのルート} にする。Bash ツールで git branch --show-current を実行し、結果が main でない場合は、何も実行せず「{ブランチ名} がチェックアウトされているため実行を見送った」と報告して終了する（結果が空の場合は {ブランチ名} を「detached HEAD」とする）。main であっても .claude/skills/paper-scout/SKILL.md に「月次自動実行モード」の節が無い場合は、何も実行せず「main の paper-scout スキルに月次自動実行モードの節が無いため実行を見送った（main が古い可能性がある）」と報告して終了する（いずれもチェックアウトの切り替え・pull はしない）。
2. Skill ツールで `paper-scout` スキルを呼び出し、スキルの「月次自動実行モード」の手順に厳密に従う。Python は conda 環境の python.exe（{masterresearch 環境の python.exe}）をフルパスで呼ぶ。出力先はこのセッションのスクラッチパッドとする。
3. 日本語本文は一時ファイルに書き出して --body-file で投稿する。
4. GitHub への書き込みは、スキルの手順にある報告 Issue の作成（初回のみ）とコメント追記だけとする。リポジトリへのコミット・push は行わない。OPENALEX_API_KEY 等の値は表示しない。
5. 完了したら、投稿したコメントの URL（または書き込まなかった理由）を報告する。失敗した場合は、どのステップで何のエラーが出たかを具体的に報告する。
```

### 2.6 monthly-reproducibility-check

対象構成・照合の規則・終了コードは [check_reproducibility.py](../scripts/check_reproducibility.py) の冒頭の説明と [reproducibility_targets.json](../scripts/reproducibility_targets.json) を正本とする。全構成の再実行に約2時間10分かかる（2026-11 時点の見込み。各構成の実測は報告の所要時間の列にある）。

ほかの定期実行と違い、`{リポジトリのルート}` のチェックアウトでは動かさず、`origin/main` から一時的な作業ツリー（detached）を作って動かす。`{リポジトリのルート}` が作業ブランチのままでも見送りにならず、2時間の実行中にブランチを切り替えられてもコードが混ざらないようにするためである。git 管理外の入力（データセットの GeoPackage）は、`--data-root` で `{リポジトリのルート}` から読む（読み取りのみ）。入力が無い構成は、再実行せずに「実行失敗（入力欠落）」として報告される。

プレースホルダは、2章の冒頭の2つに加えて、`{masterresearch 環境のルート}`（conda 環境のディレクトリを Git Bash の形式で書いたもの。例の形: `/c/Users/{ユーザー}/miniconda3/envs/masterresearch`）を使う。`{リポジトリのルート}` は区切りを `/` にして書く（Bash の文字列の中で `\` が崩れないようにするため）。

一時的な作業ツリーは `{リポジトリのルート}/.claude/worktrees/monthly-reproducibility` に置き、再実行の出力先は既定の一時ディレクトリ（`%TEMP%\reproducibility_…`）にする。長いパスを許可する OS の設定が無効な環境では、パスは 259 文字までに限られ、分析の出力名・追跡しているファイル名はそれぞれ 200 文字前後になる。セッションのスクラッチパッドのような深い場所に置くと、保存済み結果を読めない・図を保存できないためである（2026-11-26 の試し実行で、スクラッチパッドの下の出力先では図の保存が失敗した）。

```text
リポジトリ {リポジトリのルート} で分析の再現性チェックを**月次自動実行**として実行する（担当者不在のため、ユーザーへの確認は行わない）。分析スクリプトを一時的な出力先で再実行して保存済みの結果と照合し、結果を報告 Issue にコメントする。全構成で2時間以上かかる。

以下では Bash ツールを使う。{作業領域} は、このセッションのスクラッチパッドの下に作る reproducibility フォルダ（区切りは /）とし、実行ログと照合結果だけを置く。{作業ツリー} は {リポジトリのルート}/.claude/worktrees/monthly-reproducibility とする（パスの長さの上限に当たらないよう、深い場所に置かない）。

手順:
1. 作業ディレクトリを {リポジトリのルート} にし、git fetch origin main を実行する。失敗した場合は以降を行わず、エラーを報告して終了する。
2. {作業ツリー} が既にある場合（前回の実行が途中で止まった残り）は、先に git worktree remove "{作業ツリー}" で消す。消せない場合は --force を使わず、以降を行わずに報告して終了する。続けて git worktree add --detach "{作業ツリー}" origin/main で origin/main の一時的な作業ツリーを作る（{リポジトリのルート} のチェックアウトは切り替えない・pull しない）。cd "{作業ツリー}" && git rev-parse --short HEAD でコミットを控える。作業ツリーの scripts/reproducibility_targets.json に "inputs" という文字列が無い場合は、再実行せず「origin/main の再現性チェックが入力の基準ディレクトリに未対応のため見送った」と報告し、手順 7 の後片付けだけを行って終了する。
3. 次のコマンドを Bash ツールの run_in_background で実行する（2時間以上かかるため。終わると通知されるので、途中でポーリングしない）:
   cd "{作業ツリー}" && export PATH="{masterresearch 環境のルート}:{masterresearch 環境のルート}/Library/mingw-w64/bin:{masterresearch 環境のルート}/Library/usr/bin:{masterresearch 環境のルート}/Library/bin:{masterresearch 環境のルート}/Scripts:{masterresearch 環境のルート}/bin:$PATH" && PYTHONPATH="$(pwd -W)" PYTHONUTF8=1 "{masterresearch 環境のルート}/python.exe" -m scripts.check_reproducibility --all --data-root "{リポジトリのルート}" --keep-work-dir --output-json "{作業領域}/result.json" --output-md "{作業領域}/result.md" > "{作業領域}/run.log" 2>&1; echo "exit=$?" >> "{作業領域}/run.log"
4. 終わったら run.log の末尾の exit= の値で判定する。0=全構成が一致、2=不一致がある、1=実行できない構成がある（設定の不正・入力の欠落・再実行の失敗など）。result.md が無い場合は、run.log の末尾30行を報告に使う。
5. 報告 Issue を特定する: gh issue list --state open --label analysis --limit 100 --json number,title の出力を一時ファイルに保存して UTF-8 で読み、タイトルが「analysis: 分析の再現性チェック 月次レポート」と完全に一致する Issue を使う（複数あれば番号の最も小さいもの）。gh が失敗した場合は書き込まずに終了し、エラーを報告する（報告 Issue を重複して作らないため）。無い場合に限り、タイトルを上記、ラベルを analysis、本文を「scripts/check_reproducibility.py を月次で実行した照合結果を、毎月コメントで追記する。対象構成は scripts/reproducibility_targets.json、定期実行の設定は .github/scheduled-tasks.md を参照。このIssueは定期実行（monthly-reproducibility-check）により作成されました。」として gh issue create で作る。
6. コメント本文を一時ファイルに書き、gh issue comment {番号} --body-file で投稿する。本文は、1行目に「## {実行日（YYYY-MM-DD）} の再現性チェック」、続けて「- 実行したコード: origin/main {手順 2 のコミット}」「- 判定: {全構成が一致／不一致あり／実行できない構成あり}（終了コード {値}）」を置き、その後に result.md の内容（無ければ run.log の末尾30行をコードブロックで）をそのまま続ける。終了コードが 0 以外の場合は、末尾に「不一致・失敗の原因（コード・入力・ライブラリ版・非決定性のどれか）は、この報告では判定していない。各構成の来歴の差（入力・コード・ライブラリ版）を手がかりに切り分ける。」と添える。
7. 後片付け: cd {リポジトリのルート} && git worktree remove "{作業ツリー}" を実行する。失敗した場合は --force を使わず、作業ツリーが残った旨とエラーを報告に含める。再実行の出力先（run.log の「再実行の出力先:」の行にある一時ディレクトリ。構成ごとのログと再実行の出力）は消さず、そのパスを報告に含める。
8. 終了コードが 0 以外の場合に限り、PushNotification ツールが使えれば「再現性チェック: {判定}（コメントの URL）」を1行で通知する。
9. 次の操作は行わない: {リポジトリのルート} のブランチの切り替え・pull、data/output/ や docs/ の変更、リポジトリへのコミット・push、報告 Issue へのコメント（と初回の作成）以外の GitHub への書き込み。
10. 完了したら、投稿したコメントの URL、判定、構成ごとの判定の件数、合計の所要時間を報告する。失敗した場合は、どの手順で何のエラーが出たかを具体的に報告する。
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
   - `notifyOnCompletion`: `false`（登録したセッションへの完了通知は不要。結果は実行履歴で確認する）
3. 登録結果を確認する: もう一度 `list_scheduled_tasks` を実行し、`nextRunAt` が想定どおりかを確かめる。すぐに試す場合は `run_scheduled_task` を使う（手動実行と同じ扱い）
4. 本書を更新する: スケジュールやプロンプトを変えたら、本書の1章・2章も同じ内容に直す（本書が写しとして古くならないようにするため）

## 4. 運用上の注意

- 定期実行は `{リポジトリのルート}` に**その時点でチェックアウトされているブランチ**のスキル・スクリプトで動く（`main` そのものではない）。作業ブランチがチェックアウトされたままだと、古い手順や作業中の手順で動いてしまう。そのため `monthly-*` の2件と `weekly-result-staleness-check` は、冒頭で `main` 以外なら実行を見送るようにしている（見送った旨は実行履歴に残る）。手順を変えた場合は、変更を merge したうえで `{リポジトリのルート}` の `main` を最新にするまで反映されない
- `weekly-docs-consistency-check`・`weekly-digest` の2件にはこの確認を入れていない（既存の設定のまま）
- `monthly-reproducibility-check` は上の2つの型と違い、`{リポジトリのルート}` のブランチに関係なく `origin/main` の一時的な作業ツリーで動く（2.6節）。そのため、手順を変えた場合も merge すれば次回から反映される（`{リポジトリのルート}` の `main` を最新にする必要は無い）。一方で、git 管理外の入力は `{リポジトリのルート}` のものを読むため、入力のデータセットを作り直した場合は `{リポジトリのルート}` に置いた時点で次回の照合に使われる（作り直した入力で保存済み結果と照合することになり、入力の差として報告される）
- `monthly-reproducibility-check` は約2時間かかる。実行中にアプリを閉じたり PC がスリープしたりすると止まりうる（スリープ中の挙動は**未確認**）。止まった場合は作業ツリー（`{リポジトリのルート}/.claude/worktrees/monthly-reproducibility`）が残るが、次回の実行が最初に消す。再実行の出力先（`%TEMP%\reproducibility_…`）は毎回残るため、不要になったら手で消す。採用構成・採用観測・保存済み結果を変えたときは、`scripts/reproducibility_targets.json` の対象構成も直す（テストが、各構成の引数と保存済み結果に記録された設定の一致を確かめる）
- Earthdata トークンの有効期限が切れていなくても、LAADS DAAC からの取得にはプロダクトごとのデータ利用許諾への同意が別に必要である。同意していない場合も「リダイレクト先で 401」となり失効と症状が似るため、ヘルスチェックが OK でも取得に失敗したら同意状況を確認する
- 実行時の権限モードは、登録したセッションのモードではなく **Claude Code の既定のモード**になることがあり、その場合はツールの承認待ちで止まりうる。登録後にアプリのスケジュール欄から一度「今すぐ実行」して必要なツールを承認しておくと、承認内容がタスクに保存され、以後の実行で自動適用される
- PushNotification がスケジュールタスクの実行セッションで使えるかは**未確認**である。使えない場合でも、実行結果はアプリのスケジュールタスクの実行履歴から確認できる

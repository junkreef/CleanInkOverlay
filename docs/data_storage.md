# データの保存 (SQLite + Alembic)

記録は SQLite の 1 ファイル (`data/splatoon.db`) に入る。DB 層は `app/db/` (SQLAlchemy のモデル・クエリ・Alembic の移行)。読み書きは全部 `app/store.py` の `Store` を通る。

## スキーマ (`app/db/models.py`)

### matches (1 試合 1 行)

| 列 | 中身 |
|---|---|
| `started_at` | タイマー開始 (t0) のローカル時刻 (ISO)。録画はファイル名の時刻 + 動画内の秒 |
| `mode` / `rule` / `stage` | バナーの署名のラベル (リザルト表、無ければ個人パネル)。`rule` はバナーに無ければルール画面のルール名 |
| `result` | win / lose / draw |
| `my_pct` / `enemy_pct` | ナワバリの塗り % (ナワバリ以外は NULL) |
| `my_count` / `enemy_count` / `knockout` / `my_team_points` / `enemy_team_points` | ガチのカウント ([ranked_rules.md](ranked_rules.md#カウントとチームのポイント)) |
| `duration_s` | t0 から最後に HUD が見えたときまで |
| `source` | `live` か録画のファイル名 |
| `rule_image` / `result_image` / `medal_image` | 保存した画面 (リポジトリからの相対パス) |
| `raw_json` | パーサーの出力 (リザルト表の各行、`stage_id` / `mode_id` / `rule_id` / `title_id`、行の `weapon_unknown` など)。あとでラベルを付けたときに列を埋めるのに使う |
| `notes` | 例外的な保存の理由 (`no rule screen`、`no result screen: result and counts from the judge screen`、`own row and stage from the result panel`、`restarted without rule screen` など) |

### match_players (1 試合 8 行、HUD のスロット順)

`slot` (0〜3 味方、4〜7 敵 = ルール画面のカードの並び)、`team` (ally / enemy)、`is_self`、`weapon` (不明なら NULL)、`weapon_score`、`weapon_conf`、`points`、`kills_assists`、`deaths`、`specials`、`result_row` (チームの中の 0〜3)、`link_score` (スロットとリザルト行の紐づけの一致度、NULL = 並びは任意)。

リザルト表の無い試合は、個人パネルの自分の行だけが入る。プレイヤー名は記録しない。

### events (時系列の出来事)

`t_ms` (t0 からのミリ秒)、`clock` (その時刻のタイマー表示 '2:38')、`type`、`slot`、`target_slot`、`weapon`、`source`、`confidence`、`duration_ms`。

| type | slot | target_slot | source |
|---|---|---|---|
| `death` | やられた人 (8 人) | — | `hud` (イカ枠、duration = X の長さ) |
| `kill` | 自分 | たおした相手 (名前の署名で決まれば) | `killfeed` |
| `killed_by` | 自分 | 倒した相手 (吹き出しのカードで決まれば) | `bubble` |
| `special` | 自分 | — | `gauge` |
| `special_ready` | 自分 (ゲージが満タンになった) | — | `gauge` |

`type` には CHECK 制約がある。`weapon` (吹き出しのブキ名) は今は入れていない。

### timeline (毎秒、自分の HUD)

`t_s` (t0 からの整数秒) ごとに 1 行。HUD の見えない秒は行なし。

| 列 | 中身 |
|---|---|
| `points` | 右上の塗りポイント (ナワバリ。NULL = 読めない) |
| `gauge` / `ready` | スペシャルゲージの量 (その秒の中央値) / 満タンだったか |
| `obj_pos` / `obj_holder` / `my_best` / `enemy_best` | ヤグラ / ホコの位置 (−100〜+100)、乗っている側、各チームの進み (0〜100) |
| `my_count` / `enemy_count` | ガチエリア / アサリのカウント (`obj_holder` = 箱の光っている側) |
| `my_penalty` / `enemy_penalty` | ガチエリア / アサリの「+N」(0 = なし、NULL = 読めない) |
| `overtime` | 延長中だった秒は 1 |

### medals / weapons

- `medals`: `match_id`、`name` (ラベル、未ラベルなら署名 id)、`rank` (gold / silver)、`position` (画面の上から)、`sig_id`。
- `weapons`: ブキの分類 (`assets/weapons.json`、`python -m app.db init` で入れる)。統計のまとめ用。

## 移行 (Alembic)

- リビジョン: `0001_baseline` (SQLAlchemy 化した時点のスキーマ)、`0002_team_points` (matches のチームのポイント)、`0003_objective_timeline` (timeline の obj_* / カウント / overtime)、`0004_area_penalty` (timeline のペナルティ)。
- **既存のファイルは頼まれたときだけ移行する** (配布版では、起動のたびにランチャーが頼む: [release.md](release.md#ランチャー-applaunchpy))。`Store()` は、無い (か空の) ファイルは現行のスキーマで作るが、リビジョンが古いファイルは `SchemaOutdated` (次のコマンドを案内するメッセージ) で開かない。移行はバックエンドを止めてから:

  ```
  uv run python -m app.db upgrade [--db PATH]
  ```

  - 既存のファイルに触る前に、WAL をチェックポイントしてから `<db>.bak-<日付>-<旧リビジョン>` に写す (同名があれば番号を足す)。
  - 移行は 1 トランザクションで走る (途中で失敗しても元のまま)。
  - 状態の確認は `uv run python -m app.db current` (ファイルのリビジョンとコードの head)。
- `alembic_version` の無いファイル (SQLAlchemy 化より前の `work/db.py` 時代) はもう扱わない。
- **スキーマの変え方**: `app/db/models.py` を直す → `uv run alembic revision --autogenerate -m "説明"` → `app/db/migrations/versions/` に出たファイルを**必ず読んで直す** (SQLite なので batch モード。CHECK 制約や列の削除は反映されないことがある) → `uv run python -m app.db upgrade` で適用。モデルと最新リビジョンの差分が無いことはテストで確かめる (`tests/test_db.py`)。

CLI (`python -m app.db`):

```
uv run python -m app.db init      [--db PATH]   # 作る / 移行する + ブキの分類を入れる
uv run python -m app.db upgrade   [--db PATH]   # 最新のリビジョンへ (先にバックアップ)
uv run python -m app.db current   [--db PATH]   # ファイルとコードのリビジョン
uv run python -m app.db stats     [--db PATH]   # Web と同じ統計の表
uv run python -m app.db matches   [--db PATH]   # 自分の試合の一覧
```

## 接続と書き込み

- 接続ごとに `PRAGMA foreign_keys = ON`、`journal_mode = WAL` (`app/db/engine.py`)。レコーダーのスレッドと Web のワーカーが同じファイルを同時に読み書きできる。
- Store は読み取りのたびに Session を作り、書き込みだけプロセス内の RLock で直列にする。
- 子テーブル (match_players / events / timeline / medals) は試合の削除で消える (ON DELETE CASCADE)。
- DB のファイルをコピーしてバックアップを取るときは、`-wal` が残っていると中身が古いことがある。SQLite の backup か、上の `upgrade` のようにチェックポイントしてから写す。

## 統計 (`app/db/queries.py`)

`Store.stats(since, mode, rule)` / `GET /api/stats?since=&mode=&rule=` が返す表:

| 名前 | 中身 |
|---|---|
| `overview` | 自分の試合の合計・平均 (見出しの数字)。カウントのある試合があれば KO 勝ち / 負け、平均カウント |
| `weapon_stats` | 自分のブキ別 |
| `rule_stats` | ルール別 (KO 勝 / KO 負) |
| `stage_stats` | ステージ別 |
| `enemy_weapon_stats` | 相手のブキ別: 遭遇数 (人 / 試合)、遭遇した試合の勝ち数と勝率、やられた回数、たおした回数 |
| `medal_stats` | 表彰の種類別 |
| `my_timeline` | 自分のキル / デスを 30 秒刻みで |
| `daily_stats` | 日別 |

- `since`: 省略 / `all` = 全部、`today`、`session` (配信セッションの開始以降)、`7d` (今日とその前の 6 日)、ISO 時刻。`mode`: モード名。`rule`: ルール名か `@gachi` (ガチ全部 = カウントが読めた試合か、ルール名が「ガチ…」の試合)。
- 自分の行の無い試合は集計から外れる。

## 画像と JSON

- 画面の PNG は `samples/matches/{stamp}_{rule|result|medals|judge}.png`、試合 JSON は `samples/matches/{stamp}.json`。`{stamp}` はライブなら保存時刻 (`YYYY-MM-DD_HH-MM-SS`)、録画なら `{ファイル名}_{動画内の秒}`。
- 証拠の画像は `samples/bubbles/` と `samples/misses/` ([recorder.md](recorder.md#証拠の画像))。
- Web からは `/files/{path}` で `samples/`・`work/frames/`・`data/icon_samples/` の下だけを配る。

### 画像の掃除

バックエンドの起動時に `Store.prune_images` が、`config.toml` の `images.keep_days` (既定 7) 日より古い (ファイルの更新時刻) 画面 PNG と証拠 JPG を消す。

- 残すもの: 未ラベルの署名が写っている画面 (ラベル付けのページで使う)、試合 JSON。
- 消した画面を指している `matches` の画像の列は NULL にする。
- 何を残すかはファイルだけで決まる (以前は git で管理しているファイルを残していたが、git の無い配布版では何も消えなかった)。

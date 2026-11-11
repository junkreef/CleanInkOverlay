# 構成と動かし方

## 4 つの部品

| 部品 | 場所 | 役割 |
|---|---|---|
| Store | `app/store.py` (`Store`) | SQLite (`data/splatoon.db`)、画像ファイル (`samples/`)、署名ライブラリ (`assets/signatures.json`)、ブキアイコンのライブラリ (`assets/weapon_icons_captured/` + `data/icon_samples/`) への**唯一の入口**。ネットワークサーバーではなく import して使う |
| レコーダー | 解析エンジン `work/recorder.py` (`Recorder`)、フレームループと CLI は `app/recorder.py` | 映像のフレームを受け取り、画面を判定して試合を組み立て、Store に保存する。エンジンはフレームと Store しか見ない |
| Web バックエンド | `app/backend.py` (FastAPI + uvicorn) | REST と WebSocket `/ws`。`--live` ならレコーダーを同じプロセスのスレッド (`RecorderRunner`) で動かす。`web/dist` があれば `/` で配信 |
| フロントエンド | `web/` (React + Vite)、オーバーレイは `web/overlay.html` | 試合一覧・詳細・統計・ラベル付け ([web_ui.md](web_ui.md)) |

画像解析のコードは `work/*.py` にある。主なもの:

| ファイル | 読むもの |
|---|---|
| `recorder.py` | 状態機械、試合の組み立て ([recorder.md](recorder.md)) |
| `hud.py` | 試合中の HUD ([hud.md](hud.md)) |
| `scan_screens.py` (`looks_like_rule`)、`rule_screen.py` | ルール画面の判定、カード、ルール名 |
| `result_parser.py`、`live_result_watch.py` (`looks_like_result`) | リザルト表、グリフ集、バナー ([result_screens.md](result_screens.md)) |
| `judge.py`、`counts.py` | ジャッジくん画面の勝敗・%、ガチのカウント |
| `panel.py`、`medals.py` | 個人パネル (自分の行)、表彰 |
| `schedule.py` | 「スケジュールが更新されました」 |
| `objective.py`、`area.py` | ガチヤグラ / ホコの線、ガチエリア / アサリのカウント ([ranked_rules.md](ranked_rules.md)) |
| `weapon_match.py`、`weapon_icons.py` | ブキアイコン ([weapon_icons.md](weapon_icons.md)) |
| `signatures.py` | 署名ライブラリ ([signatures.md](signatures.md)) |
| `live_capture.py` | キャプチャデバイスの検索 |
| `phase_check.py` | 録画を 6 つの位相で通して比べる確認用 ([recorder.md](recorder.md#サンプリングと位相)) |
| `eval_icons.py`、`harvest_icons.py`、`rebuild_signatures.py` | 開発用の評価・作り直しのスクリプト |

Store はプロセス内のイベントバスも持つ (`store.events.subscribe(topic, cb)` / `publish`)。topic は `match_saved` / `match_deleted` / `signatures_changed` / `weapon_icons_changed`。バックエンドはこれをそのまま WebSocket に流す。別プロセスで動くレコーダーのために、1 秒おきの最新の試合 id の監視も併用する。

## 環境

- Python は uv で管理する (`pyproject.toml`、バージョンは `.python-version`、opencv-python / numpy / FastAPI / uvicorn / pygrabber / SQLAlchemy / Alembic、開発用に pytest)。`uv sync` で `.venv` を作る。uv をユーザー site に入れた場合は `python -m uv ...` で呼ぶ。
- フロントエンドは Node + npm (React 18 + Vite 5)。`cd web && npm install && npm run build` で `web/dist` を作る。開発中は `npm run dev` (:5173) から :8000 へプロキシ。
- ライブ取り込みは Windows の DirectShow (OpenCV の `CAP_DSHOW`)。既定の入力は OBS Virtual Camera。

## 動かし方

```
uv run python -m app.backend                       # Web UI だけ (http://127.0.0.1:8000)。記録は画面のボタンで開始 / 停止
uv run python -m app.backend --live [--device N]   # Web UI + レコーダー (OBS Virtual Camera)
uv run python -m app.recorder --live               # レコーダー単独 (Ctrl-C か --minutes まで)
uv run python -m app.recorder --video FILE [--from 秒 --to 秒]   # 録画を解析
```

共通のオプション: `--db PATH` (既定 `data/splatoon.db`)、`--dry` (DB に書かない)。レコーダーの `--debug` はサンプルごとの JSON も保存する。バックエンドは `--port` / `--host` も取る。

- **ダブルクリック起動**: `CleanInkOverlay.bat` (UI だけ。3 秒後にブラウザを開く。`.venv` や `web/dist` が無ければ `uv sync` / npm build もする) と `CleanInkOverlay_live.bat` (レコーダーも起動)。中身は `python -m uv sync` → `python -m uv run python -m app.backend` で、venv や管理 Python が壊れていても uv が作り直す。
  - bat は **ASCII のみ** にする。日本語を含む UTF-8 の bat は `chcp 65001` のあと cmd の読み取り位置がずれてコマンドが壊れる (`uv sync` が `ync` になった)。
  - `start.bat` という名前は cmd の `start` と衝突するので使わない。
- **レコーダーの開始 / 停止** は Web UI のヘッダーから (`POST /api/recorder/start {device?, dry?}` / `POST /api/recorder/stop`、デバイス一覧は `GET /api/recorder/devices`)。
  - デバイス列挙は pygrabber (COM) なので、それに触るスレッド (FastAPI のワーカー、レコーダーのスレッド) は先に `comtypes.CoInitialize()` が要る (`app.recorder._com_init`)。
  - 「OBS Virtual Camera」は OBS が仮想カメラを止めていてもデバイスとして見えるので、開けても映像が来ない (IDLE のまま) ことがある。
- 録画は **FFmpeg を名指しして開く** (`cv2.CAP_FFMPEG`)。読み取りは FFmpeg で復号したコマに合わせてあり、OpenCV が代わりに使う Windows 標準のデコーダー (MSMF) では画素の値が変わって結果が崩れる (2026-11-12、同じ録画でルール不明・ステージなし・8 人中 4 人のブキが None・キル数 32)。FFmpeg のプラグイン (`cv2/opencv_videoio_ffmpeg*.dll`) が無ければ案内を出して止まる。配布版 (zip) にも同梱している ([release.md](release.md#同梱している-ffmpeg-lgpl))。
- **録画の解析** は 60 fps の動画を `round(fps / 10)` コマおき (60 fps なら 6 コマに 1 コマ) に読む。ライブは 60 fps のコマを毎回 `grab()` し、0.1 秒ごとに解析するコマだけ `retrieve()` する (追いつき方は `nxt += 0.1`)。
- テストは `uv run pytest` (`tests/`)。テスト用の画面は `work/frames/` にある。
- **配布版 (zip)** は Python ごと入っていて、`CleanInkOverlay.bat` が `app.launch` を動かす (データフォルダの用意、DB の移行、ログ、ブラウザ)。作り方は [release.md](release.md)。

## ファイルの置き場所

下の表の「配布しない」ものと `config.toml` は**データフォルダ** (`app.paths.DATA_ROOT`) の下にある。git の作業ツリーではリポジトリのルートそのもの、配布版では `%LOCALAPPDATA%\CleanInkOverlay` で、プログラムのフォルダには書き込まない (環境変数 `CLEANINK_HOME` で変えられる)。配布版では、`assets/signatures.json` と `assets/weapon_icons_captured/` に使う人が足した分もデータフォルダの同じパスに入る ([release.md](release.md#プログラムのフォルダとデータフォルダ-apppathspy))。

| 場所 | 中身 | 配布 |
|---|---|---|
| `data/splatoon.db` | 記録 (SQLite、WAL) | しない |
| `samples/matches/` | 試合ごとの画面 PNG (`{stamp}_rule.png` / `_result.png` / `_medals.png` / `_judge.png`) と試合 JSON (`{stamp}.json`、`--debug` なら `{stamp}_samples.json`) | しない |
| `samples/bubbles/` | やられた吹き出しの照合の証拠 (相手カードの切り出し + その時刻のフレーム) | しない |
| `samples/misses/` | 吹き出しの出なかった自分のデスの前後のコマを並べた画像 | しない |
| `data/icon_samples/` | ブキアイコンのサンプル (リザルト行の切り出し) と未知アイコンのグループ | しない |
| `assets/weapon_icons_captured/` | 自前のブキアイコンのテンプレート (RGBA 56 px) | する |
| `assets/glyphs/` | 数字のグリフ集 | する |
| `assets/signatures.json` | 署名ライブラリ (ステージ・表彰などの名前) | する |
| `assets/weapons.json` | ブキの分類 (統計のまとめ用、`python -m app.db init` で DB の `weapons` に入る) | する |
| `work/templates/` | 判定用のテンプレート画像 (やられた!、復活まで、表彰の見出し、WIN! / LOSE...、ノックアウト!、延長中!、マップの ×、スケジュール更新) | する |
| `assets/weapon_icons/` | wiki のブキアイコン。ライセンスが無いので**配布しない**。開発用ツールが手元にあれば使うだけ ([weapon_icons.md](weapon_icons.md#wiki-アイコンの扱い)) | しない |

`samples/` の画面は溜まり続けるので、バックエンドの起動時に `Store.prune_images` が古いものを消す ([data_storage.md](data_storage.md#画像の掃除))。

## 設定 (`config.toml`)

任意。`config.example.toml` (全項目と既定値) を、データフォルダの `config.toml` に写して変える。無い項目は既定値、知らない項目や不正な値はキー名を出して止まる (`app/config.py`)。

| キー | 既定 | 意味 |
|---|---|---|
| `[images] keep_days` | 7 | `samples/` の画面 PNG と証拠 JPG を残す日数 |
| `[overlay] adobe_fonts_kit` | `""` | オーバーレイの数字用 Adobe Fonts の Web プロジェクト ID。空なら Google Fonts の Rubik Black |

# CleanInkOverlay

スプラトゥーン3（日本語 UI）のキャプチャ映像を読んで、試合の記録を自動で残すツールです。
リザルト画面・試合中の HUD・ルール画面を画像解析して、勝敗・塗りポイント・キル/デス・スペシャル・武器・ステージ・
ガチルールのカウントなどを SQLite に保存し、Web 画面で戦績を見たり、配信用のオーバーレイに出したりできます。

## できること

- **自動記録**：OBS 仮想カメラ（またはキャプチャデバイス）の映像から、試合の開始〜リザルトを検出して記録
- **戦績**：試合一覧・試合詳細（キル/デスのタイムライン、ガチルールのカウント推移）・統計ダッシュボード
  （武器別・ステージ別・相手の武器別・メダル・日別）
- **配信オーバーレイ**：OBS のブラウザソース用ページ（`/overlay`）に、配信セッション中の戦績を表示
- **ルール**：ナワバリバトル、ガチエリア / ヤグラ / ホコ / アサリ、イベントマッチ、フェスマッチ

## 使いはじめる（Windows 用の zip）

Python などを入れる必要はありません。

1. [Releases](https://github.com/junkreef/CleanInkOverlay/releases/latest) から `CleanInkOverlay-v○○-win64.zip` をダウンロードして、
   **すべて展開**します（展開したフォルダーは好きな場所に置けます）。
2. [OBS Studio](https://obsproject.com/ja) でゲームの映像を映し、「仮想カメラ開始」を押します。
3. 展開したフォルダーの `CleanInkOverlay.bat` をダブルクリックします。ブラウザに画面が出たら、右上の「● 記録開始」を押します。

あとはふつうに試合をするだけで、リザルト画面が出るたびに試合が 1 行増えます。
配信に戦績を出す方法、記録の置き場所、うまく動かないときの見方は、zip の中の
[はじめにお読みください.txt](packaging/はじめにお読みください.txt) にあります。

### 必要なもの

- Windows 10 / 11（64 ビット）
- OBS Studio と、ゲームの映像を PC に取り込む機器（キャプチャーボードなど）
- 1920x1080 のゲーム映像、ゲームの表示言語は日本語。OBS の仮想カメラには**ゲームの画面だけ**がいっぱいに映るようにします
  （枠などを重ねたシーンを配信している場合は、仮想カメラの出力タイプを「ソース」にしてゲームの映像のソースを選びます）

### 知っておいてほしいこと

- **はじめて起動するときの警告**：個人で作っているツールで、ファイルに発行元の署名がありません。「Windows によって PC が
  保護されました」と出たら、「詳細情報」→「実行」で起動します。
- **記録の置き場所**：`%LOCALAPPDATA%\CleanInkOverlay`（`OpenDataFolder.bat` で開きます）。展開したフォルダーの中には
  何も保存しないので、新しいバージョンにするときは新しい zip を展開して起動するだけです。記録はそのまま引き継がれます。
- **通信**：自分の PC の中（`127.0.0.1`）だけです。記録や映像を外に送ることはありません（オーバーレイのページだけ、
  数字のフォントを Google Fonts から読み込みます）。
- **まだ作者の環境でしか確かめていません**。ほかのキャプチャー機器や OBS の設定でうまく読めないことがあれば、
  [Issues](https://github.com/junkreef/CleanInkOverlay/issues) で教えてください。分かっている制限は
  [docs/limitations.md](docs/limitations.md) にあります。

### 名前を付けてほしいもの

ステージ名・表彰・武器アイコンのうち、まだ知らないものは「未知」として保存され、Web 画面の「未知のステージ・表彰」で
一度名前を付けると以後は自動で認識されます。武器アイコンは作者のリザルト画面から切り出したテンプレート
（`assets/weapon_icons_captured`）で照合していて、メイン 174 種の全部が入っています。

## ソースから動かす（開発する人向け）

必要なもの：Windows、Python（起動スクリプトが `python -m uv` で [uv](https://docs.astral.sh/uv/) を入れ、uv が `.python-version` の
Python と依存パッケージを用意します）、Node.js（Web 画面のビルド）。

```bat
CleanInkOverlay.bat          :: Web 画面だけ起動 (http://127.0.0.1:8000)。録画はページから開始/停止
CleanInkOverlay_live.bat     :: Web 画面 + OBS 仮想カメラからの記録を同時に開始
```

初回はパッケージのインストールと Web 画面のビルドが走るので、少し時間がかかります。手動で動かす場合：

```bat
python -m uv sync
cd web && npm install && npm run build && cd ..
python -m uv run python -m app.backend [--live] [--device N]
```

設定を変えたいときは `config.example.toml` を `config.toml` にコピーして編集します（画像の保存日数、オーバーレイのフォントなど）。

### データの置き場所

ソースから動かすときは、リポジトリのフォルダーがそのままデータの置き場所です（どれも git の管理外）。
zip 版では同じ並びが `%LOCALAPPDATA%\CleanInkOverlay` の下にできます（環境変数 `CLEANINK_HOME` で変えられます）。

| 場所 | 中身 |
|---|---|
| `data/splatoon.db` | 試合の記録（初回起動時に作成）。スキーマ更新は `python -m uv run python -m app.db upgrade`（zip 版は起動時に自動） |
| `samples/` | 解析に使ったリザルト画面などの画像。`config.toml` の `keep_days` より古いものは起動時に削除 |
| `data/icon_samples/` | 武器アイコンのサンプル（テンプレートの作り直しに使う） |

### テストと構成

```bat
python -m uv run pytest
```

- `app/`：Web バックエンド（FastAPI）、データ保存（SQLAlchemy + Alembic）、zip 版のランチャー（`app/launch.py`）
- `work/`：画像解析と記録処理（レコーダー、リザルト解析、HUD、武器照合など）と開発用ツール
- `web/`：Web 画面とオーバーレイ（React + Vite）
- `tests/`：テスト。`work/frames/` の実際のゲーム画面を使います
- `tools/`、`packaging/`：zip 版のビルドとスモークテスト、同梱する bat と説明書
- `docs/`：画面解析の仕組みの解説

`work/phase_check.py` は録画を 6 通りのサンプリング位相で流して結果のぶれを確認するツールです
（映像は 60fps、解析は 6 フレームに 1 回）。`work/eval_icons.py` と `work/harvest_icons.py` は、手元に参照用の
武器アイコン一式（`assets/weapon_icons`、配布していません）があるときだけ使えます。

### zip 版を作る

```bat
python tools/build_release.py     :: dist/CleanInkOverlay-v<version>-win64.zip
python tools/smoke_release.py     :: その zip を、何も入っていない PC と同じ条件で起動してみる
```

`v<version>` のタグを push すると、GitHub Actions が同じことをして、zip を付けた下書きのリリースを作ります。
くわしくは [docs/release.md](docs/release.md)。

## ライセンス

[MIT](LICENSE)

### 配信・動画で使うとき

配信や動画には自由に使えます（収益化していても構いません）。このツールの画面が映っている配信・動画では、説明欄（概要欄）の
どこかにこのリポジトリへのリンクを入れてください。いちばん下など、目立たないところで構いません。

```
戦績表示: CleanInkOverlay https://github.com/junkreef/CleanInkOverlay
```

改造したものや、これをもとに作ったものを使う場合も、同じようにこのリポジトリへのリンクをお願いします。
改造版を配るときは、この項も残しておいてもらえるとうれしいです。

スプラトゥーン3は任天堂の著作物です。このリポジトリのテスト用画像・テンプレート画像はゲーム画面から切り出したもので、
著作権は任天堂に帰属します。本ツールは任天堂とは関係のない非公式・非営利のファンツールです。

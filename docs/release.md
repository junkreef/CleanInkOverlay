# 配布パッケージ (Windows 用 zip)

Python も git も入っていない PC で、zip を展開して `CleanInkOverlay.bat` をダブルクリックするだけで動く形。
使う人向けの説明は [`packaging/はじめにお読みください.txt`](../packaging/はじめにお読みください.txt) (zip に同梱)。このページは作る側の話。

## 方式

- **Python ごと入れた zip** を GitHub Releases に置く。python.org の embeddable package (インストール不要の Python 本体) に、
  `uv.lock` どおりの依存パッケージ、ビルド済みの Web 画面、プログラム本体を足したもの。約 73 MB、展開して約 200 MB。
- インストーラーは使わない。展開した場所でそのまま動き、消せば終わり。レジストリやスタートメニューには触らない。
- PyInstaller などで 1 つの exe に固めない。理由:
  - 固めた exe は署名が無く、ウイルス対策ソフトの誤検知が多い。embeddable の `python.exe` は Python Software Foundation の署名付き。
  - ソースの配置が git の作業ツリーと同じなので、パスの扱いを 2 通り持たなくて済む (`app.paths.ROOT` はどちらでもプログラムのフォルダ)。
- 署名はしていないので、ダウンロードした zip の bat を初めて実行すると SmartScreen の警告が出る (「詳細情報」→「実行」)。

## zip の中身

```
CleanInkOverlay/
  CleanInkOverlay.bat            runtime\python\python.exe -X utf8 -m app.launch
  CleanInkOverlay_live.bat       同じ + --live (起動と同時に記録開始)
  OpenDataFolder.bat             データフォルダをエクスプローラーで開く
  はじめにお読みください.txt
  LICENSE  THIRD_PARTY_NOTICES.txt  pyproject.toml  config.example.toml
  app/  work/  assets/           git で管理しているファイルのうち実行に要るもの (work/frames と assets/real_icons は除く)
  web/dist/  web/overlay.html    ビルド済みの Web 画面、オーバーレイ
  web/licenses/                  Web 画面の JavaScript に入っているパッケージ (React など) のライセンス本文
  runtime/python/                Python 本体 + Lib/site-packages (依存パッケージ)
```

- 入るのは `git ls-files` に出るファイルだけ。手元にしか無いもの (wiki のアイコン、`samples/`、DB) は構造的に入らない。
- `runtime/python/python314._pth` が `sys.path` の全部 (標準ライブラリ、`Lib\site-packages`、2 つ上 = プログラムのフォルダ)。
  環境変数 `PYTHONPATH` やユーザーの site-packages は見ないので、PC に別の Python があっても混ざらない。
- bat は ASCII のみ・CRLF。zip の中の bat を展開せずに実行した人には、日本語のメッセージボックスを出す
  (PowerShell の `[regex]::Unescape` に `\uXXXX` で渡す)。

### 同梱している FFmpeg (LGPL)

opencv-python には、動画ファイルを読むための FFmpeg が DLL (`cv2/opencv_videoio_ffmpeg500_64.dll`) で付いてくる。zip にもそのまま入れている。

- 録画の解析 (`python -m app.recorder --video FILE`) はこのデコーダーでないと正しく読めない ([architecture.md](architecture.md#動かし方))。ライブの取り込み (DirectShow) は cv2 本体だけで動く。
- 中身は OpenCV プロジェクトがビルドした FFmpeg n7.1 + libvpx v1.16.0 + aom v3.14.1 で、GPL や non-free の部品は入っていない (DLL の中の configure の行に `--enable-gpl` / `--enable-nonfree` が無い)。ライセンスは **LGPL 2.1 以降**。
- LGPL のバイナリを配るので、`THIRD_PARTY_NOTICES.txt` に次を書いている: 何であるか、ライセンス (本文は `cv2\LICENSE-3RD-PARTY.txt`)、差し替えてよいこと、ビルド元 (`opencv/opencv_3rdparty` のコミット `06dc20ca…`、ブランチ `ffmpeg/5.x_20260602`) と、そこにあるソース取得スクリプト (`ffmpeg/download_src.sh`)・ビルドスクリプト。ソースのアーカイブそのものはリリースに付けていない (opencv-python を同梱するほかのプロジェクトと同じやり方。2026-11-12 の判断)。
- これらの事実は `build_release.py` の `FFMPEG_PLUGIN` に、DLL の MD5 と一緒に固定してある。opencv-python を上げて DLL が変わるとビルドが止まるので、OpenCV の `3rdparty/ffmpeg/ffmpeg.cmake` (バイナリのコミットと MD5)、そのコミットの `ffmpeg/download_src.sh` (各ソースのタグ)、DLL の中の configure の行を見直して書き換える。

同梱しているものとそのライセンスの一覧は、ビルド時に `THIRD_PARTY_NOTICES.txt` として zip の直下に書き出す (Python のパッケージは各 `dist-info`、Web 画面の JavaScript のパッケージは `web/licenses/` に本文がある)。

## プログラムのフォルダとデータフォルダ (`app/paths.py`)

配布版では、新しいバージョンを**別のフォルダに展開しても記録が引き継がれる**ように、使う人のものはプログラムのフォルダに置かない。

| | git の作業ツリー | 配布版 |
|---|---|---|
| `ROOT` (プログラム: `app/` `work/` `assets/` `web/dist`) | リポジトリのルート | 展開したフォルダ。**書き込まない** |
| `DATA_ROOT` (データ) | 同じくリポジトリのルート | `%LOCALAPPDATA%\CleanInkOverlay` |

- `DATA_ROOT` は環境変数 `CLEANINK_HOME` で決まる (無ければ `ROOT`)。配布版のランチャー (`app.launch`) が、未設定なら
  `%LOCALAPPDATA%\CleanInkOverlay` を入れる。`app.paths` を import した時点で読むので、ランチャーは import の前に設定する。
- データフォルダの中はリポジトリと同じ並び: `data/splatoon.db`、`data/icon_samples/`、`samples/`、`config.toml`、
  それに `logs/` と、下の「使う人が足した分」。
- DB に入る画像のパス (`samples/matches/...png`) はデータフォルダからの相対パス (`Store.rel`)。

### 配布したライブラリと、使う人が足した分

署名ライブラリ (`assets/signatures.json`) とブキのテンプレート (`assets/weapon_icons_captured/`) は、配布物でありながら
実行中に書き足される。配布版ではこれを 2 か所に分ける (`Store(shipped_assets=...)`、既定で `ROOT != DATA_ROOT` のとき)。

- **署名** (`signatures.Library(path, shipped=)`): 配布された `ROOT/assets/signatures.json` を先に読み、
  `DATA_ROOT/assets/signatures.json` には**配布版と違うものだけ**を書く (新しい id、自分で付けた名前)。
  - 新しいバージョンが名前を増やせば、全員に届く。自分で付けた名前は自分のものが勝つ。
  - 手元で名前の無かった id に新しい配布版が名前を付けていたら (`Library.adopted`)、`Store.signatures()` が、その id で
    保存済みの試合・表彰にも名前を入れる (`Store._fill_label`、名前を付けたときと同じ処理)。
- **ブキのテンプレート** (`weapon_icons.IconLibrary(captured_dir, samples_dir, shipped_dir=)`): 配布されたテンプレートを
  先に読み、手元のサンプルから作り直したテンプレートは `DATA_ROOT/assets/weapon_icons_captured/` に書いて、以後そちらが勝つ。
  レコーダーが読むのも両方のフォルダ (`IconLibrary.template_dirs` → `weapon_match.load_captured_icons`)。

git の作業ツリーでは `shipped` が無く、今までどおり `assets/` の下をそのまま読み書きする (作者はそれをコミットして配布物を更新する)。

## ランチャー (`app/launch.py`)

コマンドラインの無い人のために、作業ツリーでは手でやることを起動時に済ませる。

1. データフォルダを決めて作る。標準出力・標準エラーを `logs/<起動時刻>.log` にも書く (新しい 20 個を残す)。
2. ポート (既定 8000) に誰がいるかを見る (`probe`): CleanInkOverlay が動いていればブラウザを開くだけ、ほかのアプリなら案内して終わる。
3. `config.example.toml` をデータフォルダに写す (設定を変える人はそれを `config.toml` にコピーする)。
4. **DB を今のスキーマに移行する** (`app.db.upgrade`、移行の前に `<db>.bak-<日付>-<旧リビジョン>` へバックアップ)。
   - `Store` 自身は今までどおり古いファイルを開かない ([data_storage.md](data_storage.md#移行-alembic))。頼むのがランチャーに変わるだけ。
   - DB のリビジョンをこのバージョンが知らない (= 新しいバージョンで作った記録を古いバージョンで開いた) ときは、何も触らずに
     「最新版を使ってください」と出して終わる (`known_revisions`)。
5. サーバーが応答したらブラウザを開き、`app.backend` を動かす。知らないオプション (`--live`、`--device N`) はそのまま渡す。

失敗したときは bat が `pause` するので、メッセージとログの場所が読める。

## 作り方

```
python tools/build_release.py              # dist/CleanInkOverlay/ と dist/CleanInkOverlay-v<version>-win64.zip
python tools/smoke_release.py              # その zip を、使う人と同じ条件で起動してみる
```

ビルドに要るもの (作る側の PC だけ): git、uv、Node.js。

- `build_release.py`: 管理下のファイルを写す → `npm ci && npm run build` → embeddable package をダウンロード
  (`dist/cache/`、SHA-256 を `PYTHON_SHA256` と照合) → `uv export` + `uv pip install --target` で依存パッケージ →
  `THIRD_PARTY_NOTICES.txt` → 検査 (必須ファイル、FFmpeg の DLL が `FFMPEG_PLUGIN` のものであること、テンプレートの数、パスの長さ ≤ 150 文字) → zip。
  - Python のバージョンは `.python-version` (テストを走らせるのと同じもの)。上げるときは `PYTHON_SHA256` に足す。
    足す前に、展開した `python.exe` の署名が Python Software Foundation のものか確かめる (`Get-AuthenticodeSignature`)。
  - パスの長さを見るのは、エクスプローラーの展開が 260 文字を超えるパスで失敗するため。
- `smoke_release.py`: zip を**日本語と空白を含むフォルダ**に展開し、Python も git も Node も PATH に無い環境と空のユーザー
  プロファイルで bat から起動して、次を確かめる。
  - Web 画面・オーバーレイ・API が応答する (ブキ 174 種、未知の署名 0)。
  - パッケージのレコーダーが `work/frames/` のテスト画面を読める (`tools/smoke_frames.py`: 各画面の判定とリザルト表のブキ・ステージ)。
  - DB・ログがデータフォルダにでき、プログラムのフォルダには何も書かれていない。
- 日本語のフォルダで試すのは、`cv2.imread` が ANSI コードページ外の文字を含むパスを開けないため。Windows のユーザー名が
  日本語だと、ダウンロード先もデータフォルダも日本語のパスになる。プログラムの中の画像は `weapon_icons.imread_u`
  (`np.fromfile` + `cv2.imdecode`) で読み、書くほうは `cv2.imencode(...).tofile()` を使う。**実行時のコードで `cv2.imread` /
  `cv2.imwrite` を使わない**。

## リリースの手順

1. `pyproject.toml` の `version` を上げ (`uv lock` で `uv.lock` も合わせる)、そのバージョンで変わったことを `docs/release_notes/v<version>.md` に書いてコミットし、main に push する。このファイルがリリースの説明の先頭に入る (無ければ省かれる)。
2. `git tag v<version>` を push する。GitHub Actions ([`.github/workflows/build.yml`](../.github/workflows/build.yml)) がテスト →
   ビルド → スモークテストを走らせ、zip を付けた**下書き**のリリースを作る (タグと `version` が違えば失敗する)。
3. GitHub の Releases で下書きを確かめ、説明を足して「Publish release」を押す。

タグの無い push でも同じビルドとスモークテストが走り、zip は Actions の成果物 (artifact) に残る。

## 分かっている弱いところ

- **作者の環境でしか確かめていない**。キャプチャーボード、OBS の色の設定や拡大縮小が違うと、同じ画面でも画素が変わる。
  ブキアイコンの照合などは「ライブの取り込みは無劣化」を前提にしている ([limitations.md](limitations.md))。
- コード署名が無い (SmartScreen の警告)。
- 更新の通知は無い。新しい zip を自分で取りに行く。
- DirectShow の取り込みと COM (pygrabber) は Windows 専用。

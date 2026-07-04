# ヤフオク出品トラッキング自動化

3アカウント（さーぱす／サーパス／surpass）のヤフオク出品を追跡し、SQLiteに蓄積、Googleスプレッドシートへ自動反映、ダッシュボードHTMLを生成するローカルツール。

出品は2系統で管理する：
- **自分の出品（source=manual）**: `input/new_urls.txt` に貼り付けたURLのみ。「自分が出品したものだけチェックしたい」場合はこちらをダッシュボード/シートでフィルタする
- **アカウント全体（source=auto）**: 3アカウントの出品者ページを毎回自動クロールして検出した全出品（2026/7/1以降出品分のみ、`config/settings.json`の`discover_since`で変更可）

同じ出品がどちらの経路でも見つかった場合は「自分の出品」を優先して保持する。

## セットアップ（初回のみ）

### 1. 依存ライブラリ（すでにvenv作成・インストール済み）
```
cd ~/yahoo-auction-tracker
./venv/bin/pip install -r requirements.txt
```

### 2. 既存データの取り込み（任意）
claude.aiで作成した `出品トラッキング_0704更新.xlsx` を取り込む場合（取り込んだ行はすべて「自分の出品」として登録される）：
```
./venv/bin/python3 -m src.importer "/path/to/出品トラッキング_0704更新.xlsx"
```

### 3. Google Sheets連携用のOAuthクライアント作成
サービスアカウントキーは組織ポリシー（`iam.disableServiceAccountKeyCreation`）でブロックされることがあるため、OAuth方式（初回のみブラウザでログイン許可、以降はトークン自動更新）を使う。

1. https://console.cloud.google.com/ でプロジェクトを作成（または既存を利用）
2. 「APIとサービス」→「ライブラリ」で **Google Sheets API** と **Google Drive API** を有効化
3. 「APIとサービス」→「OAuth同意画面」で外部/内部いずれかを選び、アプリ名など最低限の情報を入力して保存（自分しか使わないので審査は不要。公開ステータスは可能なら「本番環境」にしておく — 「テスト」のままだとトークンが7日で失効する）
4. 「認証情報」→「認証情報を作成」→「OAuthクライアントID」→アプリケーションの種類は**デスクトップアプリ**を選択
5. 作成後にJSONをダウンロードし、`config/oauth_client.json` として配置
6. 対象スプレッドシート（`config/settings.json`の`spreadsheet_id`）を開いて、自分のGoogleアカウント（このOAuthでログインするアカウント）がすでにオーナー/編集者になっていることを確認（通常は自分のシートなので追加共有は不要）
7. 初回のみ、ターミナルで `./venv/bin/python3 main.py sync` を実行するとブラウザが開くのでログイン・許可する。成功すると `config/token.json` にトークンが保存され、以降は自動更新される（`main.py all`のlaunchd自動実行でもブラウザ操作は不要になる）

## 日次の使い方

### 自分の出品を追加する
1. `input/new_urls.txt` を開き、`# YYYY/M/D` の行の下にその日出品したURLを貼り付ける
2. 実行:
```
./venv/bin/python3 main.py add
```
- 各URLを並列取得し、商品名・価格・入札数・出品者IDなどをSQLiteに `source=manual` で登録
- 出品者IDが `config/accounts.json` に無い場合は「要確認」として警告表示 → 新しいIDが出てきたらこのファイルに追記する
- 処理後、コンソールに日別サマリー（件数・入札率）を表示
- 処理済みの `new_urls.txt` は `input/processed/` に日時付きでアーカイブされ、本体は空になる

### アカウント全体・既存出品の状態を更新する（手動 or 自動）
```
./venv/bin/python3 main.py discover  # 3アカウントの出品者ページを丸ごとクロールし、新規出品を自動検出・既存分の価格/入札数を更新
./venv/bin/python3 main.py recheck   # DB内で出品中の行を再取得（discoverで確認できなかった＝終了した可能性がある行のみ個別に取得）
./venv/bin/python3 main.py sync      # Googleスプレッドシートへ全件反映
./venv/bin/python3 main.py dashboard # output/dashboard.html を再生成
./venv/bin/python3 main.py all       # discover→recheck→sync→dashboardをまとめて実行（自動実行はこれを使う）
```
`discover`は出品者ページ（1アカウントにつき1〜数リクエスト、50件/ページ）だけで済むため、`add`の頃のように出品1件ずつページを取得する必要がなく非常に効率的。個別ページ取得(`recheck`)は「今回のdiscoverで見当たらなくなった＝終了した可能性がある行」だけに絞られる。

## 自動実行（launchd）
毎日12:00・19:00・22:30の3回、`main.py all`（アカウント全体クロール→個別再チェック→シート同期→ダッシュボード再生成）を自動実行する設定です。
自分の出品の追加(`add`)は手動貼り付けが前提のため自動実行の対象外です。

セットアップ:
```
cp launchd/com.piroegg.auctiontracker.recheck.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.piroegg.auctiontracker.recheck.plist
```

停止・解除する場合:
```
launchctl unload ~/Library/LaunchAgents/com.piroegg.auctiontracker.recheck.plist
```

ログは `data/launchd.log` / `data/launchd.err.log` に出力されます。

## ダッシュボードのフィルタ
`output/dashboard.html` の「登録元」フィルタで「自分の出品のみ」「アカウント全体（自動検出）」を切り替えられる。他のフィルタ（日程・アカウント・入札有無・状態・検索）と併用可能。

## ファイル構成
- `main.py` — CLIエントリポイント（add / discover / recheck / sync / dashboard / all）
- `src/scraper.py` — 非同期でヤフオクの商品ページ・出品者ページを取得し、埋め込まれたJSON（`__NEXT_DATA__`）から情報を抽出
- `src/db.py` — SQLiteスキーマとupsert処理（`source`列で自分の出品/アカウント全体を区別）
- `src/sheets_sync.py` — gspreadでGoogleスプレッドシートへ全件書き込み
- `src/dashboard.py` — DBの内容からダークテーマのHTMLダッシュボードを生成
- `src/importer.py` — 既存xlsxの初回インポート
- `src/dateutil_local.py` — 出品日の表記ゆれ（`2026/7/2` と `2026/07/02`）を統一する小さなヘルパー
- `config/accounts.json` — 出品者ID→アカウント表示名のマッピング
- `config/settings.json` — スプレッドシートID、`discover_since`（自動検出の対象開始日）などの設定
- `config/oauth_client.json` — （要配置）GoogleのOAuthクライアントID（デスクトップアプリ）。取り扱い注意、外部共有しないこと
- `config/token.json` — （初回`sync`実行後に自動生成）認証済みトークン。これも外部共有しないこと

## 注意事項
- スクレイピングは自分のアカウントの公開出品ページの読み取りのみ。同時実行数は5に制限し、識別可能なUser-Agentを設定して過度な負荷をかけないようにしている
- `config/oauth_client.json` と `config/token.json` にはGoogleアカウントへのアクセス情報が含まれるため、絶対に外部に共有・アップロードしないこと

# LINE 連携ステータス表示システム

LINE のリッチメニューから開く公開ステータスページ（`/status`）と、
ボタン操作だけで状態を更新できる管理画面（`/admin`）。

- **技術スタック**: Next.js（App Router）/ Supabase（DB + Auth）/ Vercel
- **時刻の扱い**: 表示・入力とも日本時間（Asia/Tokyo）固定。DB には timestamptz で保存する。

| パス | 認証 | 内容 |
|---|---|---|
| `/` | 不要 | `/status` へリダイレクト |
| `/status` | 不要 | 現在の対応状況。Realtime + ポーリングで自動更新 |
| `/admin` | 必要 | 状態の更新（マジックリンクでログイン） |
| `/auth/callback` | — | マジックリンクの着地点 |

---

## 1. Supabase の準備

### 1-1. スキーマを作る

Supabase ダッシュボード > SQL Editor で
[`supabase/migrations/0001_provider_status.sql`](supabase/migrations/0001_provider_status.sql)
の内容をそのまま実行する。次のものが作られる。

- `provider_status` テーブル（`id = 1` の 1 行のみで運用。初期値は `available`）
- `provider_admins` テーブル（更新を許可するユーザーの許可リスト）
- RLS ポリシー
  - **SELECT**: `anon` を含む全員に許可（公開ページから誰でも読める）
  - **UPDATE**: `provider_admins` に登録済みの認証ユーザーのみ
  - **INSERT / DELETE**: ポリシーを作らない＝誰も実行できない
- `updated_at` を必ず DB 側で打ち直すトリガー（クライアントの値を信用しない）
- `provider_status` の Realtime 配信の有効化

### 1-2. サインアップを無効化する

Authentication > Providers > Email で **Enable sign ups を OFF** にする。
これで、あらかじめ登録したユーザー以外にはログインリンクが発行されない。

### 1-3. 自分のユーザーを作って管理者に登録する

1. Authentication > Users > **Add user** で自分のメールアドレスのユーザーを作る。
2. [`supabase/migrations/0002_register_admin.sql.example`](supabase/migrations/0002_register_admin.sql.example)
   のメールアドレスを自分のものに書き換えて SQL Editor で実行する。

`provider_admins` に載っていないアカウントでログインすると、管理画面は
「権限がありません」と表示され、API を直接叩いても RLS で UPDATE が通らない。

### 1-4. リダイレクト URL を許可する

Authentication > URL Configuration の **Redirect URLs** に次を追加する。

```
http://localhost:3000/auth/callback
https://<デプロイ先ドメイン>/auth/callback
```

---

## 2. ローカルでの起動

```bash
npm install
cp .env.local.example .env.local   # 値を自分のプロジェクトのものに書き換える
npm run dev
```

`.env.local` に必要な値は 2 つだけ（Supabase の Settings > API から取得）。

| 変数 | 内容 |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | プロジェクト URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon（public）キー |

- <http://localhost:3000/status> … 公開ページ
- <http://localhost:3000/admin> … 管理画面

環境変数が未設定でもビルドと起動は通り、画面に設定手順が表示される。

その他のコマンド:

```bash
npm run build       # 本番ビルド
npm run typecheck   # 型チェック
```

---

## 3. Vercel へのデプロイ

1. Vercel でこのリポジトリを import する（Next.js は自動検出される）。
2. Settings > Environment Variables に `NEXT_PUBLIC_SUPABASE_URL` と
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` を登録する（Production / Preview 両方）。
3. デプロイ後、`https://<ドメイン>/status` が表示されることを確認する。
4. 手順 1-4 の Redirect URLs に本番ドメインを追加したか確認する。

---

## 4. 画面の仕様

### 公開ステータスページ `/status`

認証不要。`provider_status` の `id = 1` を読んで表示する。

| DB の状態 | 表示 | 配色 |
|---|---|---|
| `busy` | 対応中 / 「20:00 まで」 | 暖色（赤系） |
| `busy` かつ `until_time` を過ぎている | 対応中（延長中） | 暖色（橙系） |
| `break` | 休憩中 / 「20:30 から対応可能」 | 中間色（黄土系） |
| `available` | 対応可能です | 寒色（青緑系） |

- LINE 内ブラウザ前提のモバイル最適化（大きな文字、状態ごとの全画面配色、セーフエリア対応）。
- 更新の反映は Supabase Realtime の購読で即時。切断時は 30 秒ごとのポーリングに落ちる
  （Realtime 接続中も 60 秒ごとに保険で取り直す）。
- 画面を再表示したタイミングでも取り直すので、LINE 内ブラウザで戻ってきたときに古い表示が残らない。
- 「延長中」の判定はクライアント側の時計で 20 秒ごとに再評価する。

### 管理画面 `/admin`

- 未ログインならログインフォーム（マジックリンク）を表示する。
- 「対応中」「休憩中」「空き」の 3 ボタン。
  - **対応中** … 終了予定時刻を入力（15 分刻み、`+15分 / +30分 / +1時間 / +2時間` のショートカット付き）して送信。
  - **休憩中** … 次に対応できる時刻を入力して送信。
  - **空き** … 時刻入力なし。タップした時点で即時反映。
- 現在時刻より前の時刻を入力した場合は翌日として扱う（深夜またぎ対応）。
- 更新の成否はトーストで表示する。RLS で弾かれた場合も「権限を確認してください」と表示する。

---

## 5. スコープ外（LINE 側の設定）

デプロイ後、LINE Official Account Manager 上で以下を設定する。

- リッチメニュー画像の作成
- 該当ボタンのアクションタイプを「URL」にし、`https://<デプロイ先ドメイン>/status` を指定

---

## 補足

リポジトリ直下の `index.html`（送金コスト試算ツール）は、この Next.js アプリからは配信されない。
引き続き同じドメインで公開したい場合は `public/` 以下に移動し、`/` 以外のパス
（例: `public/soukin/index.html` → `/soukin/`）で配置する。

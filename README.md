# Menu Photo Pro — Web版

料理写真を、料理そのものは変えずにプロ品質のメニュー写真へ仕上げる有料Webアプリです。
利用者は登録ページでID・パスワードを作成し、Stripeでチケットを購入して使います（写真1枚＝チケット1枚）。

## 構成

| ファイル | 役割 |
| --- | --- |
| `app.py` | 画面（ログイン・新規登録・写真加工・チケット購入・会員管理） |
| `auth.py` | パスワードのハッシュ化と照合 |
| `db.py` | 会員・チケット・購入記録の保存（Supabase） |
| `billing.py` | チケットの決済（Stripe Checkout） |
| `supabase_setup.sql` | Supabaseに作るテーブルと関数 |
| `make_password_hash.py` | 管理者アカウント用のパスワードハッシュ作成 |

## 初期設定

### 1. Supabase

1. https://supabase.com でプロジェクトを作成。
2. SQL Editor に `supabase_setup.sql` の中身を貼り付けて実行。
3. Project Settings → API Keys から、プロジェクトのURLと **secret key**（`sb_secret_...`、古いプロジェクトでは `service_role` key）を控える。
   このキーは全データを操作できるので、Secrets以外には書かないでください。

### 2. Stripe

1. 商品カタログで商品（例：「20枚パック」）を作り、**一回限り**の価格を設定。
2. 作成された価格ID（`price_...`）を控える。パックごとに繰り返す。
3. 開発者 → APIキー から **シークレットキー**（`sk_live_...`、テスト中は `sk_test_...`）を控える。

### 3. Streamlit Secrets

App Settings → Secrets に以下を設定。

```toml
OPENAI_API_KEY = "sk-..."

SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_SERVICE_KEY = "sb_secret_..."

STRIPE_SECRET_KEY = "sk_test_..."
APP_URL = "https://xxxx.streamlit.app"   # このアプリの公開URL（決済後の戻り先）

# 任意：設定すると登録時に同意チェックが必須になります
TERMS_URL = "https://example.com/terms"

[admins]
admin = "pbkdf2_sha256$600000$..."

[[plans]]
name = "20枚パック"
credits = 20
price_id = "price_..."

[[plans]]
name = "50枚パック"
credits = 50
price_id = "price_..."
```

## 管理者

`[admins]` のアカウントはチケットなしで使え、「会員管理」タブで会員一覧の確認とチケットの付与ができます。
追加するときは手元のPCで `python3 make_password_hash.py` を実行し、表示された1行を `[admins]` の下に貼り付けます。

## チケットの仕組み

- 購入ボタン → Stripeの決済ページ → 支払い後にアプリへ戻るとチケットが加算されます。
- 決済後にブラウザを閉じてしまっても、次回ログイン時か「お支払い済みのチケットを反映」ボタンで加算されます。
- 同じ支払いが二重に加算されることはありません。
- 写真の加工に失敗した場合、その写真のチケットは自動で返却されます。
- 同じ端末でログインに5回続けて失敗すると、5分間ログインできなくなります。

### 注意
写真の加工1回ごとにOpenAI APIの利用料金が発生します。チケット価格はAPI料金と決済手数料を上回るように設定してください。

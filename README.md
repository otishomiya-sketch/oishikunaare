# Menu Photo Pro — Web版

## 公開手順

1. このフォルダをGitHubの新しいリポジトリへアップロード。
2. Streamlit Community Cloudでそのリポジトリを選択してDeploy。
3. StreamlitのApp Settings → Secretsに以下を設定。

```toml
OPENAI_API_KEY = "sk-..."

# デモ利用管理のGoogleスプレッドシート（URLの /d/ と /edit の間の文字列）
DEMO_SHEET_ID = "1kk1hpaVJjlNtNnw_uoQxg2sGXZ0kFYFchVpAMB_e_Z8"

# Google Cloudのサービスアカウントの鍵（JSON）の中身を、そのままTOML形式で
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

利用者にはAPIキーを入力させず、サーバー側のSecretからOpenAI APIを呼び出します。

## デモ利用制限

### お店の使い方
1. 公式LINEで、全店に同じアプリのリンク（`https://7ayyryczawpyuggappqsqqd.streamlit.app`）を送る。
2. お店は初回だけ「お店の名前」を入れて「デモを始める」を押す。そのお店用の枠が自動で作られる。
3. 同じスマホなら、次からはLINEのリンクを開くだけで続きから使える（コードをブラウザに記憶）。

特別扱いしたいお店には、お店ごとのリンク（`?code=demo-xxxxxx`）を個別に送ることもできます。

### 管理表（Googleスプレッドシート「Menu Photo Pro デモ利用管理」）

1枚目：お店ごとの行。LINEから登録したお店は自動で追加されます。

| 列 | 内容 |
| --- | --- |
| A お店 | 画面に「〇〇 さま」と表示される名前 |
| B コード | そのお店のデモコード |
| C 上限 | そのお店がデモで仕上げられる枚数（書き換えれば増減できる） |
| D 使用枚数 | アプリが自動で書き込む。0に戻せばリセット |
| E 最終利用日時 | アプリが自動で書き込む |
| F デモ用リンク | そのお店専用のリンク |

「設定」シート（アプリが初回に自動で作ります）：

| セル | 内容 | 初期値 |
| --- | --- | --- |
| B1 | 全店合計の上限（達するとデモ受付を終了） | 3000 |
| B2 | LINEから登録したお店の上限 | 10 |

- 写真を仕上げる前に枚数を確保し、失敗した写真の分は戻します。
- コードが `otis-` で始まる行は社内テスト用で、全店合計には数えません。
- 設定シートの変更は、アプリに反映されるまで最大5分かかります。

### Googleスプレッドシートへの接続（初回だけ）

1. Google Cloud Console でプロジェクトを作り、「Google Sheets API」を有効にする。
2. 「IAMと管理」→「サービスアカウント」で作成し、「鍵」→「鍵を追加」→「JSON」でダウンロード。
3. スプレッドシートの「共有」で、サービスアカウントのメールアドレス（`client_email`）を「編集者」として追加。
4. JSONの中身を上の `[gcp_service_account]` の形でSecretsに貼り付ける。

### 注意
写真を仕上げるたびにOpenAI APIの利用料金が発生します。
アプリ側の上限とは別に、OpenAIの管理画面でも予算の上限を設定しておいてください。

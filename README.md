# Menu Photo Pro — Web版

## 公開手順

1. このフォルダをGitHubの新しいリポジトリへアップロード。
2. Streamlit Community Cloudでそのリポジトリを選択してDeploy。
3. StreamlitのApp Settings → Secretsに以下を設定。

```toml
OPENAI_API_KEY = "sk-..."
```

利用者にはAPIキーを入力させず、サーバー側のSecretからOpenAI APIを呼び出します。

### 注意
公開URLにすると、利用者が画像編集を実行するたびにOpenAI APIの利用料金が発生します。
不特定多数に公開する場合は、認証・利用回数制限・アップロードサイズ制限などを追加してください。

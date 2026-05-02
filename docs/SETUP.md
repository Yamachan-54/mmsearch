# セットアップ詳細手順

## 前提条件

| 項目 | 確認方法 |
|------|---------|
| Python 3.11以上 | `python3 --version` |
| `git` | `git --version` |
| Mattermostへの通常ログインアクセス | ブラウザで普通にログインできる |

## 1. リポジトリ取得 & インストール

```bash
git clone https://github.com/<your-account>/mmsearch.git
cd mmsearch
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

毎回ターミナルを開き直したら `cd mmsearch && source .venv/bin/activate` で環境を有効化してください（または `~/.bashrc` 等にエイリアスを設定）。

## 2. MMAUTHTOKEN の取得

`MMAUTHTOKEN` はブラウザがMattermostのセッションを維持するためのCookieです。これを使ってAPIアクセスします。

### 取得手順

1. ブラウザで対象のMattermostにログイン
2. **F12** で DevTools（開発者ツール）を開く
3. ブラウザに応じて以下のタブを開く:
   - **Chrome / Edge**: `Application` タブ → 左の `Storage > Cookies > <MattermostのURL>`
   - **Firefox**: `ストレージ` タブ → 左の `Cookie > <MattermostのURL>`
4. Cookie一覧から **`MMAUTHTOKEN`** を探す
5. その「値（Value）」列の長い文字列をコピー

### 取得時の注意

- セッションが切れると無効になります（数日〜数週間）。切れたら `mmsearch token-refresh` で再設定
- パスワードと同等の機密情報です。**メモ・スクショ・チャット等で他人に渡さないこと**

## 3. 初期セットアップウィザード

```bash
mmsearch init
```

入力項目:

```
Mattermost URL (例: https://mattermost.example.com): <あなたのURL>
MMAUTHTOKEN (browser DevTools → Cookies):           <ペースト・非表示>
```

成功すると以下が表示されます:

```
✓ authenticated as @<your_username>
✓ config saved → /home/<user>/.config/mmsearch/config.toml
✓ token saved via keyring
✓ db initialized → /home/<user>/.local/share/mmsearch/mmsearch.db
```

## 4. 接続確認

```bash
mmsearch doctor
```

`✓ authenticated as @<your_username>` が出ればOKです。

## 5. 初回同期

```bash
mmsearch sync
```

参加チャンネル数と過去投稿量に応じて、初回は数分〜数十分かかります。チャンネル単位で進捗バーが出ます。

### 初回同期の見積もり

| 投稿総数 | おおよその所要時間 | DB容量 |
|---------|------------------|--------|
| 〜1,000件 | 数秒 | < 1MB |
| 〜10,000件 | 1〜2分 | 数MB |
| 〜100,000件 | 10〜20分 | 数十MB |

実数値はネットワーク・サーバ負荷で変動します。途中で `Ctrl+C` で中断しても、**チャンネル単位でコミット**しているので進捗は保持されます（再実行で続きから）。

## 6. 検索

```bash
mmsearch search "キーワード"
```

オプション一覧:

| オプション | 短縮 | 例 |
|-----------|------|----|
| `--channel` | `-c` | `-c general` （部分一致） |
| `--user` | `-u` | `-u alice` （完全一致） |
| `--since` | | `--since 2026-04-01` |
| `--until` | | `--until 2026-04-30` |
| `--limit` | `-n` | `-n 200` |

### 結果からブラウザで開く

検索結果の最後に表示される長い文字列（post_id）をコピーして:

```bash
mmsearch open <post_id>
```

`--print` を付けるとURLだけ表示します（クリップボードにコピーしたい場合等）。

## 7. 定期メンテナンス

| 状況 | コマンド |
|------|---------|
| 新着投稿を取り込む | `mmsearch sync` |
| トークン期限切れ | `mmsearch token-refresh` |
| 全部やり直したい | `mmsearch reset --yes && mmsearch init` |
| DBだけリセット | `mmsearch reset --db --yes && mmsearch sync --full` |

## 環境変数によるパスのカスタマイズ

XDG準拠なので以下の環境変数で保存先を変更できます:

```bash
export XDG_CONFIG_HOME=~/work/mmsearch-config
export XDG_DATA_HOME=~/work/mmsearch-data
```

例: 個人と仕事用で別プロファイルを使い分けたい場合に便利です。

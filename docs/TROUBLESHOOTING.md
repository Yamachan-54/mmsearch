# トラブルシューティング

## 認証エラー

### `auth failed: 401` / `unauthorized`

**原因**: トークンが期限切れ、または無効化された。

**対処（推奨）**:

ブラウザで対象のMattermostに再ログイン後:

```bash
mmsearch login
```

**対処（手動ペースト）**:

ブラウザCookie抽出が動かない場合は、DevToolsで取得した値を手動入力:

```bash
mmsearch token-refresh
```

### `mmsearch sync` で「no token saved」が出る

**原因**: OS keyring からトークンを取り出せない（dbus未接続のWSL/SSHセッション等でよく発生）。

**症状**: `init` 直後は動くが、ターミナルを再起動すると同じエラーが出続ける。

**対処1（推奨・恒久対応）**:

ファイル保存に切り替える:

```bash
export MMSEARCH_TOKEN_STORAGE=file
```

`~/.bashrc` または `~/.zshrc` に追記して永続化。その後:

```bash
mmsearch login
```

**対処2（毎回解消）**:

```bash
mmsearch login         # ブラウザから再取得
```

`init` で「token saved via **file**」と表示されればfile fallbackが効いており、次回以降のセッションでも問題なく動きます。

### `unauthorized (403)`

**原因**: トークンは有効だが、特定のリソースへのアクセス権限がない（権限変更・チャンネル退出など）。

**対処**: 該当チャンネルにアクセスできるかブラウザで確認。アクセスできなくなっていれば、そのチャンネルは同期対象から除外されます（自動）。

## 同期が遅い・失敗する

### 初回同期が異常に遅い

**原因**: チャンネル数・投稿量が多い、またはMattermostサーバの負荷が高い時間帯。

**対処**:

- `Ctrl+C` で中断してOK（チャンネル単位でコミットされているので進捗は保持される）
- 後で `mmsearch sync` を再実行すると続きから取得
- 特定チャンネルのみに絞りたい場合は `~/.config/mmsearch/config.toml` の `sync_channel_ids` に対象IDを記述

### `network error` / タイムアウト

**原因**: ネットワーク不安定、VPN切断、サーバ側の一時的不調。

**対処**: 数分待って `mmsearch sync` を再実行。

### `API error 429: rate limit`

**原因**: Mattermostサーバが短時間の大量リクエストを制限。

**対処**: 数分待って再実行。`sync.py` 内 `RATE_LIMIT_DELAY` を増やす（デフォルト100ms → 300ms など）と発生しにくくなる。

## 検索結果が期待通りでない

### ヒットするはずの投稿が出ない

**チェックリスト**:

1. **同期されているか?**
   ```bash
   mmsearch channels
   ```
   該当チャンネルが一覧にあり `posts > 0` か確認。

2. **最新まで同期されているか?**
   ```bash
   mmsearch sync
   ```

3. **メッセージ本文に含まれているか?** (添付ファイル名・リアクション・スレッドのrootは検索対象外)

4. **正規表現ではなく単純な部分一致で検索しているか?** 入力はリテラル文字列として扱われます。

### 全チャンネルから検索して関係ないチャンネルがヒットする

`-c <チャンネル名>` で絞り込んでください（部分一致）。

```bash
mmsearch search "実装" -c "課題"
```

## ブラウザが開かない (`mmsearch open`)

### Linux (デスクトップ)

`xdg-open` が必要です（通常はインストール済み）。手動確認:
```bash
xdg-open https://example.com
```

### WSL2

Windows側の既定ブラウザを呼ぶには以下のいずれかが必要:

**(A) `wslu` パッケージをインストール**
```bash
sudo apt install wslu       # Ubuntu/Debian
# Arch: sudo pacman -S wslu
```
→ `wslview` が利用可能になり、Pythonの `webbrowser` が自動で使う場合があります。

**(B) URLだけ表示してコピペ**
```bash
mmsearch open <post_id> --print
```
出てきたURLをWindows側のブラウザで開けばOK。

**(C) Windowsの `cmd.exe` 経由で開く（手動エイリアス）**
```bash
alias mmopen='_f() { mmsearch open "$1" --print | xargs cmd.exe /c start; }; _f'
mmopen <post_id>
```

### macOS

`open` コマンドが標準で利用可能なので問題ないはず。

## データの場所・サイズ

### DBファイルが大きすぎる

```bash
ls -lh ~/.local/share/mmsearch/mmsearch.db
```

縮小したい場合:

```bash
# 全消去 → 必要なチャンネルだけ再取得
mmsearch reset --db --yes
# config.tomlの sync_channel_ids を編集して対象を絞ってから
mmsearch sync --full
```

### 設定・データの場所を変えたい

```bash
export XDG_CONFIG_HOME=/path/to/config
export XDG_DATA_HOME=/path/to/data
```

`~/.bashrc` 等に書いておくと永続化できます。

## やり直したい

### 完全リセット

```bash
mmsearch reset --yes
mmsearch init
mmsearch sync
```

### トークンだけ入れ直し

```bash
mmsearch token-refresh
```

### DBだけ消して再同期

```bash
mmsearch reset --db --yes
mmsearch sync --full
```

## それでも解決しない場合

`mmsearch doctor` の出力と、エラーメッセージを添えて GitHub Issue でご相談ください。

> ⚠️ Issue を投稿するときは、**トークン値・URL・チャンネル名等の機密情報を必ずマスク** してください。

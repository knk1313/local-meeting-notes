# AGENTS.md

このファイルはこのリポジトリで動く AI コーディングエージェント (Claude Code / OpenAI Codex 等) が共通で参照する **絶対禁止事項と最低限のチェック** を集めた索引。

- **Claude Code**: ルート `CLAUDE.md` から `@AGENTS.md` で取り込まれる
- **OpenAI Codex**: ルート `AGENTS.md` を直接読み込む 

人間 contributor 向けの一般規約 (Issue / PR の出し方など) は [CONTRIBUTING.md](CONTRIBUTING.md) を参照。本ファイルは AI が **コードを書く・直す・出す** 際に踏み外してはいけない事項に絞る。

## プロジェクト概要

`README.md` を参照（技術スタック・ディレクトリ構成）。

## コマンド

フロントエンドの作業は `frontend/` で行う (パッケージマネージャは pnpm)。

| 用途 | コマンド |
|---|---|
| 依存インストール | `pnpm install` |
| 開発サーバ | `pnpm dev` |
| ビルド (型チェック込み) | `pnpm build` |
| Lint | `pnpm lint` |
| ビルド結果のプレビュー | `pnpm preview` |

バックエンドの作業は `backend/` で行う。仮想環境は `backend/venv`。

| 用途 | コマンド |
|---|---|
| 仮想環境の有効化 | `source venv/bin/activate` |
| 依存インストール | `pip install -r requirements.txt` |

## git 操作

**git の操作は行わない。** ブランチの作成・切り替え、`add` / `commit` / `push` / `merge` /
`rebase` / `reset` / `stash`、PR の作成はすべて人間が行う。明示的に依頼された場合のみ実行する。

コード変更は作業ツリーに残すところまでで止め、状態確認のための読み取り専用のコマンド
（`git status` / `git log` / `git diff` など）は実行してよい。

## 規約

- **コミットメッセージ**: 日本語。機能追加は `feat:` などの prefix を付ける。
- **PR**: `.github/pull_request_template.md` のフォーマットに沿う。
- **Pythonコードのコメント・ドキュメント文字列**: 日本語で記述する。

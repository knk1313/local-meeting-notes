# CLAUDE.md

## プロジェクト概要

`README.md` を参照（技術スタック・ディレクトリ構成）。

## コマンド

フロントエンドの作業は `frontend/` で行う。

バックエンドの作業は `backend/` で行う。

## git 操作

**git の操作は行わない。** ブランチの作成・切り替え、`add` / `commit` / `push` / `merge` /
`rebase` / `reset` / `stash`、PR の作成はすべて人間が行う。明示的に依頼された場合のみ実行する。

コード変更は作業ツリーに残すところまでで止め、状態確認のための読み取り専用のコマンド
（`git status` / `git log` / `git diff` など）は実行してよい。

## 規約

- **コミットメッセージ**: 日本語。機能追加は `feat:` などの prefix を付ける。
- **PR**: `.github/pull_request_template.md` のフォーマットに沿う。

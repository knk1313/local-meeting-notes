# Contributing Guide

このドキュメントは、Issue/PRの立て方から開発環境のセットアップ、コーディング規約までをまとめたガイドです。

> [!NOTE]
> 現時点では個人（または少人数）での開発が中心ですが、将来的な共同開発・AIエージェントによる自動PR作成も見据えて、運用ルールを明文化しています。

## このプロジェクトについて

ローカルで以下の機能を一気通貫で行うツールです。

```
会議の文字起こし → タスク分解 → Markdown
```

詳細な仕様・アーキテクチャは [README.md](./README.md) を参照してください。

## Issue

Issueを立てる前に、以下を確認してください。

- 重複を避けるため、似たIssueがすでに無いか検索する
- 質問・トラブルシューティングはIssueではなく Discussions を使う
  - Issueは「機能提案」「バグ報告」「設計に関する議論」のみに使う

### 実装前に設計を確認する

新機能の追加や仕様変更を行う場合、**実装前にIssueで設計・方針をすり合わせる**ことを推奨します。特に以下の箇所は影響範囲が広いため、必ず事前に議論してください。

- STT/LLMプロバイダ抽象化層（`stt/`, `llm/`）のインターフェース変更
- Markdown出力フォーマットの変更
- 音声データの取り扱い（保持/破棄のデフォルト挙動）に関わる変更

### Issueのトリアージ

- 再現しないバグ報告はクローズしてよい
- 関連するIssueは統合してよい
- 対応が完了するまでIssueはオープンのままにし、実際に解決したコミット/PRがマージされてからクローズする

## ブランチ運用

- **`main`**: 常に動作する状態を保つ。リリース相当のブランチ
- 作業ブランチは `feat/xxx`, `fix/xxx`, `chore/xxx` のように種別をprefixする

## PRの作り方

PRを作成する前に、以下を確認してください。

- タイトルには種別を示すprefixをつける
  - `feat` / `fix` / `refactor` / `perf` / `chore` / `docs` / `test`
- 1つのPRに複数種類の変更を混ぜない（粒度を適切に保つ）
- 関連するIssueがあれば `Closes #123` のように参照を含める
- Lint・テストをローカルで通してからPRを出す（コマンドは下記「テスト」参照）
- UIに変更がある場合はスクリーンショットを添付する
- `.env.example` に影響する環境変数を追加した場合は必ず更新する

### レビューの観点

- **スコープ**: PRの目的が明確か、粒度は適切か
- **セキュリティ**: APIキーの取り扱い、音声データの破棄タイミングに問題がないか
- **プロバイダ抽象化**: STT/LLMの実装がベンダー固有の詳細を上位層に漏らしていないか
- **エラーハンドリング**: 外部API（STT/LLM）呼び出し失敗時のフォールバック・リトライが考慮されているか

## 開発環境のセットアップ

### 必要なもの

- Python 3.11+
- macOS 15以降（録音にはmacOS標準の ScreenCaptureKit を使う。仮想オーディオデバイスは不要）
- Xcode Command Line Tools（録音ヘルパーを `swiftc` でビルドする）
- OpenAI API（文字起こし）と Claude API（要約）のAPIキー

### セットアップ手順

```bash
git clone https://github.com/knk1313/local-meeting-notes.git
cd local-meeting-notes/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
# .env にAPIキーを設定
```

### 起動

```bash
# 録音して会議ノートを作る（Ctrl+C で停止）
python -m app record --title "定例MTG"
```

### Mac固有の注意事項

初回の録音開始時に、ターミナルへマイクと画面収録（システムオーディオ録音）の許可を求められます。
システム設定 > プライバシーとセキュリティ で、使用中のターミナルを許可してください。

## テスト

```bash
cd backend
python -m unittest discover -s tests -t tests
```

PRを出す前にテストが通ることを確認してください。Lint ツールは現時点では導入していません。

## コーディング規約

- 型ヒント（type hints）を必須とする
- STT/LLMプロバイダは共通インターフェース（`stt/base.py`, `llm/base.py` 相当）に準拠して実装し、`main.py` 側からはプロバイダ固有の実装を意識しなくて良い構造にする
- 音声ファイル・文字起こし生データは、デフォルトで処理後に破棄する
- APIキー等のシークレットはコードにハードコードせず、`.env` 経由で読み込む

## ラベル運用

| ラベル | 用途 |
|---|---|
| `type: feat` | 新機能 |
| `type: fix` | バグ修正 |
| `type: refactor` | リファクタリング |
| `type: docs` | ドキュメント |
| `type: chore` | 雑務・依存更新等 |
| `priority: high` / `medium` / `low` | 優先度 |
| `provider: stt` / `provider: llm` | プロバイダ抽象化層に関わるもの |

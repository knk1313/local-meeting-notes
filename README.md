# local-meeting-notes

Mac で行う会議（Zoom / Meet / Teams 等）のシステム音声とマイクを録音し、文字起こし → 要約・タスク抽出 → Markdown の会議ノート生成までをローカルで行うツール。
STT と LLM は従量課金の API（OpenAI / Claude）を使い、月額固定費のかかる文字起こし SaaS を置き換える。

```
録音 (recording.wav) → 圧縮・分割 → 文字起こし (OpenAI) → 要約・タスク抽出 (Claude) → notes/*.md
```

## 準備

macOS 15 以降。録音ヘルパーを `swiftc` でビルドするため、Xcode Command Line Tools が必要。

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
```

`.env` に `OPENAI_API_KEY`・`ANTHROPIC_API_KEY`・`CLAUDE_MODEL` を設定する（Identity-linked key なら `ANTHROPIC_WORKSPACE_ID` も）。
初回の録音開始時に、ターミナルへマイクと画面収録の許可を求められる。

## 使い方

### 録音して会議ノートを作る

```sh
python -m app record --title "定例MTG" --participant "田中" --tag project-a
```

`Ctrl+C` で停止すると文字起こしと要約を行い、`notes/`（`.env` の `NOTES_DIR`）へ Markdown を保存する。
録音データは `data/recordings_YYYYMMDDHHMMSS/` に残る（git 管理外）。やり直しに使うため自動では削除しないので、不要になったら手で消す。

| オプション | 内容 |
|---|---|
| `--title` | 会議名。未指定なら日時から自動生成 |
| `--participant` | 参加者。複数指定可 |
| `--tag` | タグ。複数指定可 |
| `--keep-transcript` | 文字起こしだけの `.transcript.txt` もノートの隣に保存する |
| `--transcribe-only` | 文字起こしで止め、要約（Claude API）を呼ばない。文字起こしは `notes/` に `.transcript.txt` として保存され、あとから `python -m app note` で会議ノートにできる |

### 音声ファイルから作る

```sh
python -m app.cli ../data/meeting.m4a --title "定例MTG"
```

`--transcribe-only` は、こちらでも使える。

### 途中で失敗したときに作り直す

文字起こしは、断片が確定するたびに録音ディレクトリの `transcript.txt` へ書き足される。
要約で失敗した場合や、分割の途中で文字起こしが失敗した場合は、そこから作り直せる（STT の再実行なし）。

```sh
python -m app note ../data/recordings_YYYYMMDDHHMMSS/transcript.txt --title "定例MTG"
```

文字起こしからやり直すなら、録音ファイルをそのまま渡す。

```sh
python -m app.cli ../data/recordings_YYYYMMDDHHMMSS/recording.wav --title "定例MTG"
```

## 仕組みと制限

**録音** — macOS 標準の ScreenCaptureKit でシステム音声と既定マイクをミックスし、会議全体を 1 本の `recording.wav` に保存する。途中で分割しないので文章が切れず、文字起こしの精度が落ちにくい。録音中は画面の自動スリープを抑止する（画面が寝るとキャプチャが止まるため）。手動の画面ロックやディスプレイの切断で中断した場合は、取得できたぶんで会議ノートを作る。`.env` の `RECORDING_BLOCK_SECONDS` は録音ファイルへ書き出す単位（既定 15 秒）で、文字起こしの分割とは無関係。

**文字起こし** — OpenAI `gpt-4o-transcribe-diarize`（話者分離あり）。API の制限に合わせて次を自動で行う。

- 25MB を超える録音は `afconvert` でモノラル AAC へ圧縮する（長さに応じて、25MB に収まる最も高いビットレートを選ぶ。32kbps で約 100 分ぶんが収まる）
- 1 回あたり 1400 秒の上限を超える録音は、20 分を目安に**前後 15 秒で最も静かな位置**で分割し、断片を並行して送る。分割した場合、話者ラベルは断片ごとに振り直される
- 結果はストリームで受け取り、区間が確定するたびの位置から進み具合を % で表示する（10% ごと、または 30 秒ごと）
- 発話の無い音声は送らない。録音の経路では録音データごと破棄し、ファイル入力の経路（WAV のとき）はファイルを残したまま止める

**要約・タスク抽出** — Claude。プロンプトは `backend/app/prompts/meeting_analysis.md` で変更できる。

**失敗への備え** — キーやモデルの設定漏れは、録音前・ファイル入力時のどちらでも処理を始める前に検査して止める。クレジット残高の不足・キーの拒否は、一時的な失敗と区別して理由を表示する。

## 出力フォーマット

```markdown
---
title: "定例MTG"
date: 2026-08-17
participants: [..., ...]
tags: [meeting, project-...]
---

## 要約

- ...

### 決定事項

- ...

### 未決事項

- ...

## タスク

- [ ] タスク1（担当: ..., 期限: ...）
- [ ] タスク2

## 文字起こし

[A] 0.00s–12.50s: ...
[B] 12.75s–30.00s: ...
```

## ディレクトリ構成

```
local-meeting-notes/
├── backend/
│   ├── app/
│   │   ├── __main__.py   # `python -m app record` / `python -m app note`
│   │   ├── cli.py        # 録音・文字起こし・要約の一気通貫処理
│   │   ├── settings.py   # .env の読み込み
│   │   ├── audio/        # 音声キャプチャ・圧縮・分割・音量判定
│   │   ├── stt/          # STTプロバイダ抽象化層
│   │   ├── llm/          # 要約・タスク抽出
│   │   ├── prompts/      # LLMプロンプト
│   │   └── output/       # Markdown生成
│   ├── tests/
│   └── requirements.txt
├── data/                  # 録音データ（git管理外）
├── notes/                 # 会議ノートの出力先（git管理外）
├── .env.example
└── README.md
```

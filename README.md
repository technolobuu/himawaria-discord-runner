# Himawaria Discord 統合ランナー

HimawariaのDiscord用スクリプト `disc.py` を改変し、
別途用意したしりとりbotと、1つのDiscordクライアントで
動作させるための統合ランナーです。

## 派生元

- プロジェクト: Himawaria
- URL: https://github.com/ruesei-koseki/Himawaria
- 派生元ファイル: disc.py
- ライセンス: Mozilla Public License 2.0

## 主な変更

- しりとりbotとのDiscordクライアントの共有
- 起動時処理・メッセージ処理の統合
- Himawariaの動作先を指定した1チャンネルに限定
- チャンネル移動コマンドの無効化
- 環境変数からの共通トークン・チャンネルIDの取得

## 公開範囲

このリポジトリは、改変した `disc_combined.py` のソースを
公開するものです。単体で動作する完全な配布物ではありません。

実行にはHimawaria本体と、以下のインターフェースを持つ
別途用意した `bot.py` が必要です。

- TOKEN
- client
- async handle_ready()
- async handle_message(message)

独立した自作の `bot.py` は、このリポジトリには含まれません。

トークン、実際の設定、会話履歴、学習済み記憶は含みません。

## ライセンス

`disc_combined.py` 全体は Mozilla Public License 2.0 の下で提供します。
ライセンス全文は `LICENSE` を参照してください。

本リポジトリはHimawariaの非公式な派生物です。

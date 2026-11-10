# -*- coding: utf-8 -*-
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# 本ファイルは Himawaria (https://github.com/ruesei-koseki/Himawaria)
# の disc.py を改変し、bot.py(しりとりbot)と統合したものです。
# Himawaria由来の部分は Mozilla Public License 2.0 の条件に従い提供されます。
# 他人に配布するときは、Himawariaの LICENSE(MPL 2.0全文)を同梱してください。

"""
bot.py（しりとりbot）と Himawaria を「同じ1つのDiscord bot」で動かすランナー。

DiscordのGatewayは、同じトークンで複数のプロセスを同時起動すると
接続を取り合って互いに切断してしまうため、bot.py と Himawaria の disc.py を
別々に同時起動することはできない。
そのため、このファイルでは bot.py の client オブジェクトをそのまま使い、
その client に両方の処理を登録して1つのbotとして動かす。

使い方（/discord_bot で）:
    ./venv/bin/python disc_combined.py

前提ディレクトリ構成:
    /discord_bot/
    ├── bot.py              （しりとりbot）
    ├── disc_combined.py    （このファイル）
    ├── .env                （DISCORD_TOKEN / SHIRITORI_CHANNEL_IDS（しりとり・2つ可）/
    │                        HIMAWARIA_CHANNEL_ID（Himawaria専用・1つ））
    └── Himawaria/          （git clone したもの）
        ├── himawaria.py
        └── mybot/          （sample をコピーしたもの）
            ├── settings.json
            ├── chara_style.txt
            └── memory.json
"""

import asyncio
import datetime
import logging
import os
import random
import re
import sys
import time

from discord.ext import tasks
import discord

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Himawaria/himawaria.py を import できるようにする
HIMAWARIA_DIR = os.path.join(BASE_DIR, "Himawaria")
if HIMAWARIA_DIR not in sys.path:
    sys.path.insert(0, HIMAWARIA_DIR)

MYBOT_DIR = os.path.join(HIMAWARIA_DIR, "mybot")

# bot.py（しりとりbot）を読み込む。
# bot.py は「直接実行でない場合」は client.run() しないので、
# ここで読み込んでもbotは起動しない。
sys.path.insert(0, BASE_DIR)
import bot as shiritori  # noqa: E402

import himawaria  # noqa: E402


# =========================================================
# Himawaria を働かせるチャンネルを1つに限定する
# =========================================================
# .env の HIMAWARIA_CHANNEL_ID に書いた1つのチャンネルでのみ反応する。
# （bot.py の SHIRITORI_CHANNEL_IDS とは別の設定）

HIMAWARIA_CHANNEL_ID_RAW = os.getenv("HIMAWARIA_CHANNEL_ID", "")

if not HIMAWARIA_CHANNEL_ID_RAW.strip():
    raise RuntimeError(
        ".envにHIMAWARIA_CHANNEL_IDを設定してください。\n"
        "（Himawariaを働かせるチャンネルIDを1つ指定します）"
    )

try:
    HIMAWARIA_CHANNEL_ID = int(HIMAWARIA_CHANNEL_ID_RAW.strip())
except ValueError as error:
    raise RuntimeError(
        f"不正なチャンネルIDです: {HIMAWARIA_CHANNEL_ID_RAW}"
    ) from error


# =========================================================
# Himawaria の初期化（disc.py と同じ）
# =========================================================

himawaria_instance = None
himawaria_instance = himawaria.Himawaria(MYBOT_DIR)
himawaria.setup_logging()

time.sleep(1)


# グローバル変数の初期化（disc.py からそのまま引用）
people = [[himawaria_instance.get_settings()["myname"], 0]]
channel = None
lastMessage = None
lastUsername = "誰か"
messages = []
pin = False
yukou = False
ii = 0
i = 0
is_active_learning = True
kaisu = 0
dt = datetime.datetime.now()
hold_message = [None, None]


helpMessage = f"""==Himawaria ヘルプ==
このbotはユーザーのメッセージに自分の意思で返信するAIです。
話している人数に応じて返信頻度を下げます。
botの名前を呼ぶとそのチャンネルに来てくれます。
メンションでは呼べません。

=学習方法=
チャットのメッセージからも学習しますが、コマンドでの学習のほうが便利です。
ぬんへっへ！===下品だよ！

=強化学習=
「!bad」とメッセージを送ると、「このメッセージは悪い」と教えることができます。
「!good」とメッセージを送ると、「このメッセージは良い」と教えることができます。

=配慮コマンドについて=
botに「通常モード」というと「通常モード」になり、メッセージにbotの名前が含まれてなくても人数に応じて頻度を変えて返信します。また、沈黙が続いたときにメッセージを送信します。
botに「寡黙モード」というと「寡黙モード」になり、沈黙が続いたときにメッセージを送信しなくなります。
botに「沈黙モード」というと「沈黙モード」になり、呼ばれたときにしかメッセージを送信しなくなります。
botに「ピン」というと、チャンネルを動かなくなります。
botに「アンピン」というと、チャンネルを動けるようになります。
これらのコマンドのタイミングも学習します。"""


# トークンは .env の DISCORD_TOKEN を共通で使う
# （Himawaria/mybot/settings.json の discToken は結合版では使われない）
TOKEN = shiritori.TOKEN

# bot.py と同じクライアント＝同じbotとして動く
client = shiritori.client

mode = himawaria_instance.get_settings()["defaultMode"]

print("mode: {}".format(mode))
print("sentences: {}".format(len(himawaria_instance.get_memory()["sentence"])))


def setMode(x):
    global mode
    mode = x
    print("mode: {}".format(mode))


kaisu = 0


async def speak(result):
    global channel, people, mode, pin, lastMessage, messages, kaisu, dt, is_active_learning, i, yukou, hold_message
    try:
        print("{}: {}".format(himawaria_instance.get_settings()["myname"], result))
        pattern = re.compile(r"^!command")
        print("users: {}".format(people))
        results = result.split("\n")

        Message = ""
        for result in results:
            if bool(pattern.search(result)):
                if is_active_learning:
                    himawaria_instance.record()
                nxt = himawaria_instance.next_speak()
                com = result.split(" ")
                if com[1] == "discMove":
                    # 【1チャンネル限定】HIMAWARIA_CHANNEL_ID に固定するため、
                    # チャンネル移動は常に無効化する
                    print("チャンネル移動は無効化されています（HIMAWARIA_CHANNEL_ID に固定）")
                    himawaria_instance.receive("エラー: チャンネルの移動は無効化されています。", "!system", is_active_learning=is_active_learning)
                    messages.append(["エラー: チャンネルの移動は無効化されています。", "!system"])
                elif com[1] == "ignore":
                    pass
                elif com[1] == "setMode":
                    setMode(int(com[2]))
                elif com[1] == "saveMyData":
                    himawaria_instance.saveData()
                elif com[1] == "pin":
                    pin = True
                elif com[1] == "unpin":
                    pin = False
                elif com[1] == "saveMyData":
                    himawaria_instance.saveData()
            else:
                Message += result + "\n"
        Message = Message[:-1]
        if Message != "":
            if channel is None:
                logger.error(
                    "送信先チャンネルが未初期化です（HIMAWARIA_CHANNEL_ID=%s）。"
                    "チャンネルIDとボットの閲覧権限を確認してください。",
                    HIMAWARIA_CHANNEL_ID,
                )
                return
            async with channel.typing():
                yukou = True
                if len(Message) / 6 / mode >= 1:
                    if len(Message) / 6 / mode >= 5:
                        await asyncio.sleep(5)
                    else:
                        await asyncio.sleep(len(Message) / 6 / mode)
                else:
                    await asyncio.sleep(1)
                if yukou:
                    await channel.send(Message)
                    if is_active_learning:
                        himawaria_instance.record()
                    else:
                        hold_message = [Message, "!"]
                    nxt = himawaria_instance.next_speak()
                    if nxt:
                        print("続きを返信します")
                        await speak(nxt)

    except discord.Forbidden:
        logger.exception(
            "Discordへの送信が拒否されました（チャンネルID=%s）。"
            "ボットのチャンネル閲覧・メッセージ送信権限を確認してください。",
            getattr(channel, "id", HIMAWARIA_CHANNEL_ID),
        )
    except discord.HTTPException:
        logger.exception(
            "Discordとの通信中にエラーが発生しました（チャンネルID=%s）。",
            getattr(channel, "id", HIMAWARIA_CHANNEL_ID),
        )
    except Exception:
        # プログラム上の不具合を権限エラーと誤表示せず、元の例外を記録する。
        # 送信失敗を会話として学習させない。
        logger.exception("Himawariaの発言処理中にエラーが発生しました。")


# =========================================================
# Himawaria 側の on_ready 本体
# =========================================================

async def himawaria_on_ready():
    # Himawaria側の起動処理（disc.py の on_ready と同じ）
    global lastMessage, messages, channel
    print('ログインしました')

    # 【1チャンネル限定対応】起動直後に発言先チャンネルを把握しておく。
    # これがないと、誰も投稿する前に「沈黙を検知」で自発発言しようとしたとき
    # channel が None のままなので
    # 「エラー: チャンネルがNoneか、このチャンネルに入る権限がありません」になる。
    ch = client.get_channel(HIMAWARIA_CHANNEL_ID)
    if ch is None:
        try:
            ch = await client.fetch_channel(HIMAWARIA_CHANNEL_ID)
        except discord.HTTPException:
            ch = None
    if ch is not None:
        channel = ch
        print(f"起動チャンネルを初期化: #{getattr(ch, 'name', HIMAWARIA_CHANNEL_ID)}")
    else:
        print(f"警告: チャンネルID {HIMAWARIA_CHANNEL_ID} が見つかりません。")

    # 再接続で on_ready が複数回呼ばれても cron は1回だけ開始する
    if not cron.is_running():
        cron.start()

    himawaria_instance.receive("通知: 貴方は目を覚ましました。", "!system", is_active_learning=is_active_learning, reply=True)
    lastMessage = ["通知: 貴方は目を覚ましました。", "!system"]
    messages.append(["通知: 貴方は目を覚ましました。", "!system"])
    dt_now = datetime.datetime.now()
    himawaria_instance.receive(dt_now.strftime('%Y / %m / %d %H : %M : %S'), "!systemClock")
    lastMessage = [dt_now.strftime('%Y / %m / %d %H : %M : %S'), "!systemClock"]
    messages.append([dt_now.strftime('%Y / %m / %d %H : %M : %S'), "!systemClock"])


# =========================================================
# Himawaria 側の on_message 本体（disc.py からそのまま引用）
# =========================================================

async def himawaria_on_message(message):
    global pin, channel, people, lastMessage, messages, helpMessage, lastUsername, ii, mode, i, is_active_learning, dt, yukou, hold_message

    # 【1チャンネル限定】指定チャンネル以外の投稿は一切見ない・反応しない
    if message.channel.id != HIMAWARIA_CHANNEL_ID:
        return

    if bool(re.search("休んで(良い|いい)(わ|よ|わよ)|終了して|exit bot", message.content)) and "モジホコリ、" in message.content:
        exit()
        return

    if message.channel == channel or bool(re.search(himawaria_instance.get_settings()["mynames"], message.content)) or isinstance(message.channel, discord.DMChannel):
        username = message.author.display_name.split("#")[0]
        if message.channel != channel:
            try:
                print("チャンネルを移動しました: {}".format(message.channel.name))
                himawaria_instance.receive("!command discMove {} | チャンネル名: {}, カテゴリー: {}, トピック: {}".format(message.channel.id, message.channel.name, message.channel.category, message.channel.topic).replace("\n", " "), username)
            except:
                print("チャンネルを移動しました: {}のDM".format(username))
                himawaria_instance.receive("!command discMove {} | 誰のDMか: {}".format(message.channel.id, username).replace("\n", " "), username)
            channel = message.channel
            people = [[himawaria_instance.get_settings()["myname"], 0]]
        if message.author == client.user:
            return

        ff = False
        parts = message.content.split("\n")
        taisho = ""
        if bool(re.search("(.*?)--", parts[0])):
            taisho = parts[0].split("--")[0]
            ff = True
        for part in parts:
            if bool(re.search("(.*?)===(.*?)", part)):
                if taisho == "" or taisho in himawaria_instance.get_settings()["mynames"]:
                    if part.split("===")[0] == "":
                        himawaria_instance.learn_sentence(lastMessage[0], "!input", direct_learning=True)
                        himawaria_instance.learn_sentence(part.split("===")[1], "!output", direct_learning=True)
                    else:
                        himawaria_instance.learn_sentence(part.split("===")[0], "!input", direct_learning=True)
                        himawaria_instance.learn_sentence(part.split("===")[1], "!output", direct_learning=True)
                ff = True
        if bool(re.search("(.*?)\n==>\n(.*?)", message.content)):
            if taisho == "" or taisho in himawaria_instance.get_settings()["mynames"]:
                himawaria_instance.learn_sentence(message.content.split("\n==>\n")[0], "!input", direct_learning=True)
                himawaria_instance.learn_sentence(message.content.split("\n==>\n")[1], "!output", direct_learning=True)
            ff = True
        if ff:
            himawaria_instance.learn_sentence("!good", "!system", direct_learning=True)
            return

        ff = False
        xx = message.content.split("\n")
        for x in xx:
            if bool(re.search("(.+):- (.+)", x)):
                himawaria_instance.learn_sentence(x.split(":- ")[1], x.split(":- ")[0], direct_learning=True)
                ff = True
        if ff:
            himawaria_instance.learn_sentence("!good", "!system", direct_learning=True)
            return

        pss = []
        for ps in people:
            pss.append(ps[0])
        if username not in pss:
            people.append([username, 0])
        if message.content == "" and message.attachments == []:
            return
        if message.content == None:
            return
        additionals = ""
        for attachment in message.attachments:
            additionals += "\n" + attachment.url
            print(attachment.url)
        message.content += additionals

        if bool(re.search("沈黙モード|黙|だま", message.content)) and bool(re.search(himawaria_instance.get_settings()["mynames"]+"|モジホコリ、", message.content)):
            himawaria_instance.receive("!command setMode 0", username)
            setMode(0)
            return
        if bool(re.search("寡黙モード|静かに|しずかに", message.content)) and bool(re.search(himawaria_instance.get_settings()["mynames"]+"|モジホコリ、", message.content)):
            himawaria_instance.receive("!command setMode 1", username)
            setMode(1)
            return
        if bool(re.search("通常モード|喋って|話して|しゃべって|はなして", message.content)) and bool(re.search(himawaria_instance.get_settings()["mynames"]+"|モジホコリ、", message.content)):
            himawaria_instance.receive("!command setMode 2", username)
            setMode(2)
            return
        if bool(re.search("饒舌モード", message.content)) and bool(re.search(himawaria_instance.get_settings()["mynames"]+"|モジホコリ、", message.content)):
            himawaria_instance.receive("!command setMode 3", username)
            setMode(3)
            return
        if bool(re.search("ピン|じっとしてて", message.content)) and bool(re.search(himawaria_instance.get_settings()["mynames"]+"|モジホコリ、", message.content)):
            pin = True
            return
        if bool(re.search("アンピン|動いていい", message.content)) and bool(re.search(himawaria_instance.get_settings()["mynames"]+"|モジホコリ、", message.content)):
            pin = False
            return
        elif bool(re.search("ヘルプを表示|ヘルプ表示|show help", message.content)) and bool(re.search(himawaria_instance.get_settings()["mynames"]+"|モジホコリ、", message.content)):
            await channel.send(helpMessage)
            return
        if bool(re.search("セーブして", message.content)) and bool(re.search(himawaria_instance.get_settings()["mynames"]+"|モジホコリ、", message.content)):
            himawaria_instance.receive("!command saveMyData", username)
            print("セーブします")
            himawaria_instance.saveData()
            print("完了")
            return

        if hold_message[0]:
            himawaria_instance.receive("!command ignore", "!system", is_active_learning=True)
            himawaria_instance.receive(hold_message[0], hold_message[1], force=True)
            hold_message = [None, None]

        print("受信: {}, from {}".format(message.content, username))
        yukou = False
        if len(people) <= 2 or isinstance(message.channel, discord.DMChannel):
            himawaria_instance.receive(message.content, username, force=True)
        else:
            himawaria_instance.receive(message.content, username, force=True)
        lastMessage = [message.content, username]
        lastUsername = username
        i = 0
        is_active_learning = True
        messages.append([message.content, username])
        dt = datetime.datetime.now()


# =========================================================
# 両方の処理を1つのbotにまとめて登録
# =========================================================
#
# discord.py では同じ client に @client.event を重ねると上書きされるため、
# 「両方を呼ぶ」合体版をここで登録する。
# しりとり側の処理は bot.py 内の handle_message / handle_ready を呼ぶ。

@client.event
async def on_ready():
    # 1) しりとりbot側の起動表示
    await shiritori.handle_ready()
    # 2) Himawaria側の起動処理
    await himawaria_on_ready()

    print(f"HimawariaはチャンネルID {HIMAWARIA_CHANNEL_ID} でのみ動作します。")


@client.event
async def on_message(message):
    # 1) しりとりbotの処理（対象チャンネル以外では何もしない）
    await shiritori.handle_message(message)
    # 2) Himawariaの処理（呼ばれたチャンネル／常駐チャンネルでのみ反応）
    await himawaria_on_message(message)


# =========================================================
# 定期処理（disc.py からそのまま引用）
# =========================================================

done_zhihou = False
zhihou_span = 0


@tasks.loop(seconds=4)
async def cron():
    global people, lastMessage, messages, mode, channel, i, is_active_learning, dt, done_zhihou, zhihou_span
    try:
        dt_now = datetime.datetime.now()

        if not done_zhihou and zhihou_span <= 0:
            pattern = re.compile(r"(0|3)0 : [0-9][0-9]$")
            if bool(pattern.search(dt_now.strftime('%Y/%m/%d %H:%M:%S'))):
                himawaria_instance.receive(dt_now.strftime('%Y/%m/%d %H:%M:%S'), "!systemClock")
            done_zhihou = True
            zhihou_span = 90
        if zhihou_span > 0:
            zhihou_span -= 1

        a = []
        for person in people:
            if person[1] < (60*10)/4:
                a.append([person[0], person[1]+1])
        people = a
        pss = []
        for ps in people:
            pss.append(ps[0])
        if himawaria_instance.get_settings()["myname"] not in pss:
            people.append([himawaria_instance.get_settings()["myname"], 0])

        if mode == 1:
            if len(messages) != 0:
                if himawaria_instance.get_current_voice() != None:
                    if bool(re.search(himawaria_instance.get_settings()["mynames"], lastMessage[0])) or isinstance(channel, discord.channel.DMChannel):
                        result = himawaria_instance.speak_freely(is_active_learning=is_active_learning)
                        if result == None:
                            pass
                        else:
                            await speak(result)
                    messages = []
            if random.randint(0, 60*25) == 0 and himawaria_instance.get_current_voice() != None:
                result = himawaria_instance.speak_freely(is_active_learning=is_active_learning)
                if result == None:
                    pass
                else:
                    await speak(result)
        elif mode == 2:
            if len(messages) != 0:
                pss = []
                for ps in people:
                    pss.append(ps[0])
                aaa = ""
                for person in pss:
                    if person == himawaria_instance.get_settings()["myname"]:
                        pass
                    else:
                        aaa = aaa + person + "|"
                aaa = aaa[0:-1]

                if len(people)-1 <= 0:
                    denominator = 0
                else:
                    denominator = len(people)-1
                if bool(re.search(himawaria_instance.get_settings()["mynames"], lastMessage[0])) or isinstance(channel, discord.channel.DMChannel) or ((not bool(re.search(aaa, lastMessage[0])) or aaa == "") and random.randint(0, denominator) == 0 and himawaria_instance.get_current_voice() != None):
                    result = himawaria_instance.speak_freely(is_active_learning=is_active_learning)
                    if result == None:
                        pass
                    else:
                        await speak(result)
                messages = []
        elif mode == 3:
            if len(messages) != 0:
                pss = []
                for ps in people:
                    pss.append(ps[0])
                aaa = ""
                for person in pss:
                    if person == himawaria_instance.get_settings()["myname"]:
                        pass
                    else:
                        aaa = aaa + person + "|"
                aaa = aaa[0:-1]

                if len(people)-2 <= 0:
                    denominator = 0
                else:
                    denominator = len(people)-2
                if bool(re.search(himawaria_instance.get_settings()["mynames"], lastMessage[0])) or isinstance(channel, discord.channel.DMChannel) or ((not bool(re.search(aaa, lastMessage[0])) or aaa == "") and random.randint(0, denominator) == 0 and himawaria_instance.get_current_voice() != None):
                    result = himawaria_instance.speak_freely(is_active_learning=is_active_learning)
                    if result == None:
                        pass
                    else:
                        await speak(result)
                messages = []
        if dt_now - dt >= datetime.timedelta(seconds=20):
            if i > -2:
                i -= 1
            is_active_learning = True
            if i <= -2:
                is_active_learning = False

            dt = datetime.datetime.now()
            himawaria_instance.receive("!command ignore", "!system", is_active_learning=is_active_learning)
            pattern = re.compile(r"(0|3)0 : [0-9][0-9]$")
            if bool(pattern.search(dt_now.strftime('%Y/%m/%d %H:%M:%S'))):
                himawaria_instance.receive(dt_now.strftime('%Y/%m/%d %H:%M:%S'), "!systemClock", is_active_learning=is_active_learning)
            print("沈黙を検知")
            if (mode == 2 and random.randint(0, 14) == 0) or (mode == 3 and random.randint(0, 11) == 0) or (mode == 1 and random.randint(0, 180) == 0):
                result = himawaria_instance.speak_freely(is_active_learning=is_active_learning)
                if result == None:
                    pass
                else:
                    await speak(result)

    except:
        import traceback
        traceback.print_exc()


# =========================================================
# Bot起動
# =========================================================

if __name__ == "__main__":
    client.run(TOKEN)

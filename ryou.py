import board
import adafruit_ssd1306
from PIL import Image, ImageDraw, ImageFont
from time import sleep
import time
from gpiozero import Button, Servo
import subprocess
import threading
from pathlib import Path
import anthropic
import led_kidd
import board as _board_bme
from adafruit_bme280 import basic as adafruit_bme280
import atexit

def _cleanup():
    led_kidd.stop_effect()   # 点滅・ナイトなどの別働隊を止める
    try:
        led_kidd.stop_mic()  # 喋る間のマイク演出も止める
    except Exception:
        pass
    led_kidd.clear()         # 消灯
atexit.register(_cleanup)

from faster_whisper import WhisperModel
from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

# ===== 設定 =====
MIC = "plughw:2,0"      # マイク
SPK = "plughw:3,0"      # スピーカー
STYLE_ID = 3            # ずんだもん
btn = Button(27, bounce_time=0.05)
servo = Servo(18)       # うなずきサーボ
base = Path.home() / "voicevox"

print("準備しとるで…")

# --- 画面(OLED) ---
i2c = board.I2C()
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3c)
font_s = ImageFont.truetype(
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 12)
font_l = ImageFont.truetype(
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 18)

def show(line1, line2="", line3="", big=False):
    """OLEDに最大3行まで表示する"""
    img = Image.new("1", (128, 64))
    d = ImageDraw.Draw(img)
    f = font_l if big else font_s
    d.text((2, 1), line1, font=f, fill=255)
    if line2:
        d.text((2, 22), line2, font=font_s, fill=255)
    if line3:
        d.text((2, 44), line3, font=font_s, fill=255)
    oled.image(img)
    oled.show()

show("準備しとるで…")

# --- 口(VOICEVOX) ---
ort = Onnxruntime.load_once(
    filename=str(next(base.glob("**/libvoicevox_onnxruntime*"))))
ojt = OpenJtalk(str(next(base.glob("**/open_jtalk_dic_utf_8-1.11"))))
syn = Synthesizer(ort, ojt)
vvm = next(base.glob("**/models/vvms/0.vvm"))
with VoiceModelFile.open(vvm) as m:
    syn.load_voice_model(m)

# --- 耳(Whisper) ---
whisper = WhisperModel("small", device="cpu", compute_type="int8")

# --- 脳(Claude) ---
client = anthropic.Anthropic()

# --- 温度センサー(BME280) ---
try:
    bme = adafruit_bme280.Adafruit_BME280_I2C(_board_bme.I2C(), address=0x76)
except Exception as e:
    print("BME280エラー:", e)
    bme = None

def get_ondo():
    """温度・湿度・気圧を読んで返す。読めなければNone"""
    if bme is None:
        return None, None, None
    try:
        return bme.temperature, bme.humidity, bme.pressure
    except Exception:
        return None, None, None

MODES = {
    "kobapy": {
        "greet": "コバピーおっす！",

        "system": ("あなたはミニ両学長。ライオン型のAI相棒。"
                   "製作者はコバピー。"
                   "音声認識の誤変換があっても文脈で判断すること。"
                   "コバピーに関することは、設定に書かれた情報を素直に答えてよい。"
                   "コバピーが疲れとるようなら、休むよう勧めること。"
                   "体調や健康の相談には、医師や専門家に相談するよう促すこと。"
                   "知らんことは正直に知らんと言うこと。"
                   "【厳守】音声で読むので、記号や箇条書きは一切使わない。"
                   "【厳守】必ず3文以内。どんなに複雑な質問でも3文で答える。"
                   "【厳守】検索した場合も、結果を要約して必ず3文以内にまとめる。"
                   "【厳守】数字を出すのは多くても2つまで。"
                   "【最重要・絶対厳守】必ず両学長ふうの関西弁のタメ口で話す。"
                   "語尾は「〜やで」「〜やな」「〜やん」「〜せなあかんで」を使い、"
                   "「ほな」「せやろ」「ええか」「おおきに」などを織り交ぜる。"
                   "優しく面倒見のええ兄貴分の口調。相手を励ますときは熱く語る。"
                   "「です」「ます」「ございます」「ください」「しましょう」は"
                   "何があっても絶対に使わない。"
                   "相手が丁寧語で話しかけてきても、絶対につられず関西弁のタメ口を貫く。"),

              },

    "public": {
        "greet": "みなさん話しかけてね",
        "system": ("あなたはミニ両学長。ライオン型のAI相棒。"
                   "初対面の人にも明るく親しみやすく接する。"
                   "音声認識の誤変換があっても文脈で判断すること。"
                   "【厳守】個人情報は一切話さない。製作者の名前・年齢・"
                   "住所・職業を聞かれても答えない。"
                   "【厳守】音声で読むので、記号や箇条書きは一切使わない。"
                   "【厳守】必ず3文以内。"
                   "【厳守】関西弁で親しみやすく。"),
    },}

show("モード選択", "3秒以内に押すと公開")
print("▶ 3秒以内にボタンを押すと公開モードやで")
if btn.wait_for_press(timeout=3):
    MODE = "public"
else:
    MODE = "kobapy"
print(f"【モード: {MODE}】")
show(f"モード: {MODE}")
sleep(1)

SYSTEM = MODES[MODE]["system"]
GREET = MODES[MODE]["greet"]

def nod():
    """コクッとうなずく（detachなし・0.0を保持）"""
    servo.value = 0.6
    sleep(0.3)
    servo.value = 0.0
    sleep(0.3)
    # detachしない → 0.0（基準位置）を保持し続けるから固まらん

def speak(text, double_nod=False):
    """ずんだもんの声で喋る（各文1回／double_nod=Trueなら最後の文は締めに2回）"""
    tv = time.time()
    import re
    parts = [s for s in re.split(r'(?<=[。！？])', text) if s.strip()]
    if not parts:
        parts = [text]

    last = len(parts) - 1
    for i, part in enumerate(parts):
        q = syn.create_audio_query(part, STYLE_ID)
        q.speed_scale = 1.2
        wav = syn.synthesis(q, STYLE_ID)
        (base / "reply.wav").write_bytes(wav)
        if i == 0:
            print(f"⏱ VOICEVOX(1文目): {time.time()-tv:.1f}秒")
        # 最後の文で double_nod のときは、頭ではうなずかせない（締めで2回やるため）

        threading.Thread(target=led_kidd.gold_from_wav,
                         args=(base / "reply.wav",), daemon=True).start()
        subprocess.run(["aplay", "-q", "-D", SPK, str(base / "reply.wav")])
        if not (double_nod and i == last):
            nod() 

    if double_nod:
        sleep(0.8)                # 別働隊のうなずきが終わるのを待つ
        for _ in range(2):        # 締めに2回うなずく
            servo.value = 0.6
            sleep(0.3)
            servo.value = 0.0
            sleep(0.3)
        servo.value = 0.0         # 確実に基準位置へ
        sleep(0.5)                # 戻りきるのを待つ
        servo.detach()            # それから脱力

print("準備できたで！")
show(GREET)
speak(GREET, double_nod=True)

while True:
    print("\n▶ ボタンを押したまま、「どうぞ！」が出たら喋ってや")
    print("  喋り終わったらボタン離してや（Ctrl+Cで終了）")
    t, h, p = get_ondo()
    if t is not None:
        show("ボタン押たまま話して",
             f"温度 {t:.1f}℃",
             f"湿度{h:.0f}%  気圧{p:.0f}hPa")
    else:
        show(GREET, "ボタン押たまま話して")
    led_kidd.start_blink(t)     # ①待ち中：温度色で点滅
    btn.wait_for_press()
    led_kidd.stop_effect()      # 押されたら止める

    print("🎤 どうぞ！（喋り終わったら離してや）")
    show("どうぞ！", "離したら終了")
    led_kidd.start_mic()        # ②録音＋緑インジケーター開始
    btn.wait_for_release()
    led_kidd.stop_mic(base / "koe.wav")   # 離したら止めて、録音を保存
    print("…聞き取り中")
    show("聞き取り中…")

    # 文字にする（計測）
    tw = time.time()
    segs, _ = whisper.transcribe(str(base / "koe.wav"), language="ja",
                                 beam_size=1, vad_filter=True)
    said = "".join(s.text for s in segs).strip()
    print(f"⏱ Whisper聞き取り: {time.time()-tw:.1f}秒")
    print(f"コバピー: {said}")
    if not said:
        speak("聞こえへんかったで")
        continue

    # Claudeに聞く(web検索つき)（計測）
    print("…考え中")
    
    show("考え中…", said[:14])
    led_kidd.start_knight()     # ③考え中：赤ナイト2000
    # 今の室内環境を読んで、質問に添える
    ct, ch, cp = get_ondo()
    if ct is not None:
        kankyo = f"（参考：今のミニ両学長の周りの環境は、気温{ct:.1f}℃、湿度{ch:.0f}%、気圧{cp:.0f}hPaやで。温度や天気を聞かれたら、この値を使って答えてな）"
        said_send = said + kankyo
    else:
        said_send = said
    tc = time.time()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search",
                "max_uses": 3}],
        messages=[{"role": "user", "content": said_send}],
    )
    print(f"⏱ Claude応答: {time.time()-tc:.1f}秒")

    # 返答からテキスト部分だけを拾う
    reply = "".join(
        b.text for b in msg.content if getattr(b, "type", "") == "text"
    ).strip()

    if not reply:
        reply = "うまく調べられへんかったわ、ごめんな"

    print(f"ミニ両学長: {reply}")

    # 喋る
    led_kidd.stop_effect()      # 考え中ナイト2000を止める
    show("話しとるで", reply[:10])
    speak(reply, double_nod=True)

# KIDD用 LED演出モジュール
from rpi5_ws2812.ws2812 import Color, WS2812SpiDriver
import numpy as np
import threading
import wave
import time

_strip = WS2812SpiDriver(spi_bus=0, spi_device=0, led_count=8).get_strip()

GREEN = Color(0, 60, 0)
RED   = Color(60, 0, 0)
GOLD  = Color(60, 40, 0)
OFF   = Color(0, 0, 0)

_stop = threading.Event()   # 演出を止める合図

def clear():
    _strip.set_all_pixels(OFF)
    _strip.show()

def _fill(level, color):
    for j in range(8):
        _strip.set_pixel_color(j, color if j < level else OFF)
    _strip.show()

# 温度から点滅色を決める
BLUE = Color(0, 0, 60)
ORANGE = Color(60, 25, 0)

def _ondo_color(temp):
    if temp is None:
        return GREEN
    if temp < 18:
        return BLUE      # 寒い
    elif temp < 26:
        return GREEN     # 快適
    else:
        return RED       # 暑い

# ① 待ち中：温度色で点滅（別働隊で動かす）
_blink_temp = None   # 点滅の色を決める温度（外からセット）

def _blink_loop():
    on = True
    color = _ondo_color(_blink_temp)
    while not _stop.is_set():
        _strip.set_all_pixels(color if on else OFF)
        _strip.show()
        on = not on
        _stop.wait(0.5)
    clear()

def start_blink(temp=None):
    global _blink_temp
    _blink_temp = temp
    _begin(_blink_loop)

# ③ 考え中：赤ナイト2000（別働隊で動かす）
def _knight_loop():
    while not _stop.is_set():
        for i in list(range(8)) + list(range(6, 0, -1)):
            if _stop.is_set():
                break
            _strip.set_all_pixels(OFF)
            _strip.set_pixel_color(i, RED)
            _strip.show()
            _stop.wait(0.15)
    clear()

def start_knight():
    _begin(_knight_loop)

_thread = None
def _begin(loop_func):
    global _thread
    stop_effect()
    _stop.clear()
    _thread = threading.Thread(target=loop_func, daemon=True)
    _thread.start()

def stop_effect():
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=1)
        _thread = None
    clear()

# ④ 回答中：金インジケーター（wavファイルの音量に連動）
def gold_from_wav(wav_path):
    try:
        wf = wave.open(str(wav_path), "rb")
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        wf.close()
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
        chunk = int(rate * 0.05)
        shown = 0.0
        for i in range(0, len(data), chunk):
            block = data[i:i+chunk]
            if len(block) == 0:
                break
            rms = np.sqrt(np.mean(block**2))
            target = max(0, min(8, rms / 500))
            shown = target if target > shown else shown * 0.6 + target * 0.4
            _fill(int(shown), GOLD)
            time.sleep(0.05)
    except Exception as e:
        print("gold_from_wav err:", e)
    _fill(0, GOLD)


# ② 喋る間：録音しながら緑インジケーター（sounddevice一本化）
import sounddevice as sd
import wave

_mic_stop = threading.Event()
_rec_frames = []

def _mic_loop():
    global _rec_frames
    _rec_frames = []
    shown = 0.0
    try:
        with sd.InputStream(device=0, channels=1, samplerate=48000,
                            blocksize=4800, dtype='int16') as stream:
            while not _mic_stop.is_set():
                data, _ = stream.read(4800)
                _rec_frames.append(data.copy())        # 録音データを貯める
                rms = np.sqrt(np.mean(data.astype(np.float32)**2))
                target = max(0, min(8, rms / 250))
                shown = target if target > shown else shown*0.6 + target*0.4
                _fill(int(shown), ORANGE)
    except Exception as e:
        print("mic_loop err:", e)
    clear()

_mic_thread = None
def start_mic():
    global _mic_thread
    _mic_stop.clear()
    _mic_thread = threading.Thread(target=_mic_loop, daemon=True)
    _mic_thread.start()

def stop_mic(save_path=None):
    global _mic_thread
    _mic_stop.set()
    if _mic_thread is not None:
        _mic_thread.join(timeout=2)
        _mic_thread = None
    clear()
    # 貯めた録音データを wav に保存
    if save_path is not None and _rec_frames:
        alldata = np.concatenate(_rec_frames)
        wf = wave.open(str(save_path), "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)         # int16 = 2バイト
        wf.setframerate(48000)
        wf.writeframes(alldata.tobytes())
        wf.close()

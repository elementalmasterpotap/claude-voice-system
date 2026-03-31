#!/usr/bin/env python3
"""
voice_system.py — ультимативная голосовая система Claude Code v3.

Голос primary, мягкие WAV fallback. Очередь с приоритетами.
Автокэш новых фраз. Живой сленговый язык.

python voice_system.py --event Stop
python voice_system.py --event PreToolUse   # stdin: JSON
python voice_system.py --test
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import winsound
from datetime import datetime
from pathlib import Path

# ── Пути ─────────────────────────────────────────────────────
CONFIG_PATH = Path(os.path.expanduser("~/.claude/sound_config.json"))
CACHE_DIR = Path(os.path.expanduser("~/.claude/sounds/cache"))
SOFT_DIR = Path(os.path.expanduser("~/.claude/sounds/soft"))
PHRASES_PATH = Path(os.path.expanduser("~/.claude/sounds/phrases.json"))
LOCK_FILE = Path(tempfile.gettempdir()) / "_voice_lock"
NO_WINDOW = 0x08000000
MAX_LEARNED = 30  # макс learned фраз на событие

# ── Приоритеты (выше число = важнее) ─────────────────────────
PRIORITY = {
    "Stop": 100,
    "Notification": 90,
    "SessionStart": 80,
    "SessionEnd": 80,
    "PostToolUseFailure": 70,
    "PreCompact": 60,
    "PostCompact": 50,
    "SubagentStart": 40,
    "PreToolUse": 20,
    "PostToolUse": 10,
    "UserPromptSubmit": 5,
}

# ── Дефолтный конфиг ─────────────────────────────────────────
DEFAULT_CONFIG = {
    "enabled": True,
    "voice_enabled": True,
    "sounds_enabled": True,
    "voice_name": "ru-RU-DmitryNeural",
    "voice_rate": "+15%",
    "volume": "high",
    "quiet_hours": None,
}


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def is_quiet_hour(cfg):
    qh = cfg.get("quiet_hours")
    if not qh:
        return False
    try:
        now = datetime.now().strftime("%H:%M")
        fr, to = qh["from"], qh["to"]
        return (fr <= now <= to) if fr <= to else (now >= fr or now <= to)
    except Exception:
        return False


# ── Очередь: lock-файл — без kill, без обрывов ──────────────
def acquire_voice_lock(event_name, timeout=3.0):
    """Захватить lock. Никогда не убивает текущее воспроизведение — ждёт или сдаётся."""
    my_prio = PRIORITY.get(event_name, 10)
    deadline = time.time() + timeout

    while time.time() < deadline:
        if LOCK_FILE.exists():
            try:
                lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
                lock_time = lock_data.get("time", 0)
                age = time.time() - lock_time

                # Lock старше 6 сек = мёртвый, забираем
                if age > 6:
                    pass  # fall through to acquire
                # Низкоприоритетные — сразу сдаются, не ждут
                elif my_prio <= 30:
                    return False
                # Высокоприоритетные — ждут окончания текущей фразы (не убивают!)
                else:
                    time.sleep(0.2)
                    continue
            except Exception:
                pass  # broken lock, acquire

        # Захватываем lock
        try:
            LOCK_FILE.write_text(
                json.dumps({"event": event_name, "priority": my_prio, "time": time.time()}),
                encoding="utf-8"
            )
            return True
        except Exception:
            time.sleep(0.05)

    return False


def release_voice_lock():
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── MP3 воспроизведение ──────────────────────────────────────
def play_mp3(filepath, block=True):
    filepath = str(filepath).replace("/", "\\")
    if not os.path.exists(filepath):
        return None

    # PS скрипт: открыть, дождаться NaturalDuration, играть ровно до конца.
    # Polling HasAudio + NaturalDuration.HasTimeSpan — единственный способ
    # узнать реальную длительность MP3 через WPF MediaPlayer.
    ps_code = f"""
Add-Type -AssemblyName PresentationCore
$p = New-Object System.Windows.Media.MediaPlayer
$p.Open([Uri]::new('{filepath}'))
# Ждём пока MediaPlayer загрузит метаданные (макс 2с)
$tries = 0
while (-not $p.NaturalDuration.HasTimeSpan -and $tries -lt 40) {{
    Start-Sleep -Milliseconds 50
    $tries++
    # Нужен Dispatcher pump чтобы MediaPlayer обновил свойства
    [System.Windows.Threading.Dispatcher]::CurrentDispatcher.Invoke(
        [System.Windows.Threading.DispatcherPriority]::Background,
        [Action]{{}}
    )
}}
$p.Position = [TimeSpan]::Zero
$p.Play()
if ($p.NaturalDuration.HasTimeSpan) {{
    $ms = [int]$p.NaturalDuration.TimeSpan.TotalMilliseconds + 150
    Start-Sleep -Milliseconds $ms
}} else {{
    # Fallback: по размеру файла
    $sz = (Get-Item '{filepath}').Length / 1024
    $ms = [Math]::Max(800, [Math]::Min($sz * 80 + 400, 6000))
    Start-Sleep -Milliseconds $ms
}}
$p.Stop()
$p.Close()
"""
    tmp = Path(tempfile.gettempdir()) / "_voice_play.ps1"
    tmp.write_text(ps_code.strip(), encoding="utf-8")
    proc = subprocess.Popen(
        ["powershell", "-WindowStyle", "Hidden", "-File", str(tmp)],
        creationflags=NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if block:
        proc.wait()
    return proc


# ── WAV ──────────────────────────────────────────────────────
def play_wav(filepath, block=True):
    filepath = str(filepath)
    if not os.path.exists(filepath):
        return
    flags = winsound.SND_FILENAME
    if not block:
        flags |= winsound.SND_ASYNC
    try:
        winsound.PlaySound(filepath, flags)
    except Exception:
        pass


def play_soft(name):
    wav = SOFT_DIR / f"{name}.wav"
    play_wav(wav, block=False)


# ── Кэш с автопополнением ───────────────────────────────────
def _cache_key(text):
    """Хеш текста для имени файла кэша."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def play_cached(name, block=True):
    mp3 = CACHE_DIR / f"{name}.mp3"
    if mp3.exists():
        play_mp3(mp3, block=block)
        return True
    return False


def speak_with_autocache(text, cfg, block=True):
    """Говорит текст. Если не в кэше — генерирует и кэширует автоматически."""
    key = _cache_key(text)
    cached = CACHE_DIR / f"auto_{key}.mp3"

    # Уже в кэше?
    if cached.exists():
        play_mp3(cached, block=block)
        return

    # Генерируем через edge-tts
    try:
        import edge_tts
    except ImportError:
        speak_fallback(text)
        return

    voice = cfg.get("voice_name", "ru-RU-DmitryNeural")
    rate = cfg.get("voice_rate", "+15%")

    try:
        asyncio.run(edge_tts.Communicate(text=text, voice=voice, rate=rate).save(str(cached)))
        play_mp3(cached, block=block)
    except Exception:
        speak_fallback(text)


# ── System.Speech fallback ───────────────────────────────────
def speak_fallback(text):
    safe = text.replace("'", "''")
    ps_code = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate=2;$s.Volume=80;$s.Speak('{safe}');$s.Dispose()"
    )
    tmp = Path(tempfile.gettempdir()) / "_voice_fallback.ps1"
    tmp.write_text(ps_code, encoding="utf-8")
    subprocess.Popen(
        ["powershell", "-WindowStyle", "Hidden", "-File", str(tmp)],
        creationflags=NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ── Голос или звук (с lock) ──────────────────────────────────
def voice_or_sound(event, cached_name, soft_name, cfg, block=False):
    if cfg.get("voice_enabled"):
        if acquire_voice_lock(event):
            try:
                if play_cached(cached_name, block=True):
                    return
            finally:
                release_voice_lock()
    if cfg.get("sounds_enabled"):
        play_soft(soft_name)


def _voice_dynamic_worker(event, text, cfg):
    """Фоновый worker: говорит и освобождает lock."""
    try:
        speak_with_autocache(text, cfg, block=True)
    finally:
        release_voice_lock()


def voice_dynamic(event, text, cfg, block=True):
    """Динамическая фраза с lock + автокэш. Всегда чисто освобождает lock."""
    if not cfg.get("voice_enabled"):
        return
    if not acquire_voice_lock(event):
        return
    if block:
        try:
            speak_with_autocache(text, cfg, block=True)
        finally:
            release_voice_lock()
    else:
        # Non-blocking: в отдельном треде, lock освободится после окончания
        import threading
        t = threading.Thread(target=_voice_dynamic_worker, args=(event, text, cfg), daemon=True)
        t.start()


# ── Живой словарь фраз из phrases.json ───────────────────────
# base (несъёмные) + learned (из ответов Claude) + stats (антиповтор)

_phrases_cache = None
_phrases_dirty = False
_save_counter = 0


def _load_phrases():
    global _phrases_cache
    if _phrases_cache is not None:
        return _phrases_cache
    if PHRASES_PATH.exists():
        try:
            with open(PHRASES_PATH, encoding="utf-8") as f:
                _phrases_cache = json.load(f)
            return _phrases_cache
        except Exception:
            pass
    _phrases_cache = {}
    return _phrases_cache


def _save_phrases():
    """Сохранить phrases.json (батчево — не каждый вызов)."""
    global _phrases_dirty, _save_counter
    if not _phrases_dirty or _phrases_cache is None:
        return
    _save_counter += 1
    if _save_counter % 3 != 0:
        return  # сохраняем каждый 3-й раз
    try:
        with open(PHRASES_PATH, "w", encoding="utf-8") as f:
            json.dump(_phrases_cache, f, indent=2, ensure_ascii=False)
        _phrases_dirty = False
    except Exception:
        pass


def _force_save_phrases():
    """Принудительное сохранение (конец сессии, learn)."""
    global _phrases_dirty
    if _phrases_cache is None:
        return
    try:
        with open(PHRASES_PATH, "w", encoding="utf-8") as f:
            json.dump(_phrases_cache, f, indent=2, ensure_ascii=False)
        _phrases_dirty = False
    except Exception:
        pass


def pick(event_key):
    """Выбрать фразу с антиповтором: реже использованные — вероятнее."""
    global _phrases_dirty
    phrases = _load_phrases()
    entry = phrases.get(event_key)
    if not entry:
        return event_key  # fallback: само название события
    pool = list(entry.get("base", [])) + list(entry.get("learned", []))
    if not pool:
        return event_key
    stats = entry.setdefault("stats", {})
    # Weighted: чем реже использована — тем вероятнее
    weights = [1.0 / (stats.get(p, 0) + 1) for p in pool]
    chosen = random.choices(pool, weights=weights, k=1)[0]
    stats[chosen] = stats.get(chosen, 0) + 1
    _phrases_dirty = True
    _save_phrases()
    return chosen


def pick_tool(tool_name):
    """Фраза для конкретного инструмента."""
    key = f"tool:{tool_name}"
    phrases = _load_phrases()
    if key in phrases:
        return pick(key)
    return None


def learn_phrase(event_key, text):
    """Добавить новую фразу в learned (если уникальная). FIFO при переполнении."""
    global _phrases_dirty
    phrases = _load_phrases()
    entry = phrases.get(event_key)
    if not entry:
        return
    all_known = set(entry.get("base", [])) | set(entry.get("learned", []))
    clean = text.strip()
    if clean in all_known or len(clean) < 3 or len(clean) > 50:
        return
    learned = entry.setdefault("learned", [])
    learned.append(clean)
    # FIFO: удаляем старые если больше MAX_LEARNED
    while len(learned) > MAX_LEARNED:
        old = learned.pop(0)
        entry.get("stats", {}).pop(old, None)
    # Счётчик для авто-прегенерации кэша
    meta = phrases.setdefault("_meta", {})
    meta["learned_since_cache"] = meta.get("learned_since_cache", 0) + 1
    _phrases_dirty = True
    _force_save_phrases()


def learn_from_response(text):
    """Извлечь короткие фразы-маркеры из первой строки ответа Claude."""
    if not text:
        return
    first_line = text.split('\n')[0].strip()
    clean = re.sub(r'[*_`#\[\](){}]', '', first_line).strip()
    # Убрать псевдографику
    clean = re.sub(r'[─═━┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬│║]', '', clean).strip()
    if not clean or len(clean) < 5 or len(clean) > 40:
        return
    # Только если похоже на фразу-маркер (начало ответа, не код, не путь)
    if re.match(r'^[/\\<>{}\[\]@#$%^&*0-9]', clean):
        return
    if '/' in clean or '\\' in clean or '=' in clean:
        return
    learn_phrase("stop", clean)


# ── Извлечение summary из ответа Claude ──────────────────────
def extract_summary(text):
    if not text:
        return None
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'[*_`#\[\]()]', '', text)
    text = re.sub(r'[─═━┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬│║]', '', text)
    for line in text.split('\n'):
        line = line.strip()
        if line and len(line) > 10:
            return line[:200]
    return None


# ── Обработчики событий ──────────────────────────────────────
def handle_stop(cfg, data):
    msg = data.get("last_assistant_message", "")
    # Обучение: извлечь фразу из ответа
    learn_from_response(msg)
    summary = extract_summary(msg)
    if summary and cfg.get("voice_enabled"):
        voice_dynamic("Stop", summary, cfg, block=True)
    else:
        voice_dynamic("Stop", pick("stop"), cfg, block=True)


def handle_notification(cfg, data):
    voice_dynamic("Notification", pick("notification"), cfg, block=True)


def handle_pre_tool_use(cfg, data):
    tool = data.get("tool_name", "")
    phrase = pick_tool(tool)
    if phrase and cfg.get("voice_enabled"):
        voice_dynamic("PreToolUse", phrase, cfg, block=False)
    elif cfg.get("sounds_enabled"):
        play_soft("soft_ping")


def handle_post_tool_use(cfg, data):
    if cfg.get("sounds_enabled"):
        play_soft("soft_ping")


def handle_post_tool_use_failure(cfg, data):
    voice_dynamic("PostToolUseFailure", pick("error"), cfg, block=False)


def handle_session_start(cfg, data):
    voice_dynamic("SessionStart", pick("session_start"), cfg, block=True)


def handle_session_end(cfg, data):
    # Финальное сохранение stats перед выходом
    _force_save_phrases()
    voice_dynamic("SessionEnd", pick("session_end"), cfg, block=True)


def handle_pre_compact(cfg, data):
    voice_dynamic("PreCompact", pick("compact"), cfg, block=True)


def handle_post_compact(cfg, data):
    voice_dynamic("PostCompact", pick("compact_done"), cfg, block=False)


def handle_subagent_start(cfg, data):
    voice_dynamic("SubagentStart", pick("agent"), cfg, block=False)


def handle_user_prompt_submit(cfg, data):
    play_soft("soft_high")


# ── Диспетчер ────────────────────────────────────────────────
HANDLERS = {
    "Stop":                handle_stop,
    "Notification":        handle_notification,
    "PreToolUse":          handle_pre_tool_use,
    "PostToolUse":         handle_post_tool_use,
    "PostToolUseFailure":  handle_post_tool_use_failure,
    "SessionStart":        handle_session_start,
    "SessionEnd":          handle_session_end,
    "PreCompact":          handle_pre_compact,
    "PostCompact":         handle_post_compact,
    "SubagentStart":       handle_subagent_start,
    "UserPromptSubmit":    handle_user_prompt_submit,
}


def run_test():
    print("=== Voice System v3 Test ===")
    cfg = load_config()
    cfg["enabled"] = True
    cfg["voice_enabled"] = True

    events = [
        ("SessionStart",      {}),
        ("UserPromptSubmit",  {}),
        ("PreToolUse",        {"tool_name": "Edit"}),
        ("PreToolUse",        {"tool_name": "Bash"}),
        ("PostToolUse",       {}),
        ("PostToolUseFailure",{}),
        ("PreCompact",        {}),
        ("PostCompact",       {}),
        ("SubagentStart",     {}),
        ("Notification",      {}),
        ("Stop",              {"last_assistant_message": "Файл создан. Все тесты збс, пройдены."}),
        ("SessionEnd",        {}),
    ]
    for ev, data in events:
        tool = data.get("tool_name", "")
        label = f"{ev}:{tool}" if tool else ev
        print(f"  [{label}]...", end=" ", flush=True)
        HANDLERS[ev](cfg, data)
        time.sleep(0.5)
        print("ok")
    print(f"\n  Автокэш: {len(list(CACHE_DIR.glob('auto_*.mp3')))} фраз")
    print("=== Done ===")


def main():
    parser = argparse.ArgumentParser(description="Claude Code Voice System v3")
    parser.add_argument("--event", help="Hook event name")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--config", action="store_true")
    args = parser.parse_args()

    if args.test:
        run_test()
        return
    if args.config:
        print(json.dumps(load_config(), indent=2, ensure_ascii=False))
        return
    if not args.event:
        return

    cfg = load_config()
    if not cfg.get("enabled", True) or cfg.get("volume") == "mute" or is_quiet_hour(cfg):
        return

    stdin_data = {}
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
            if raw.strip():
                stdin_data = json.loads(raw)
        except Exception:
            pass

    handler = HANDLERS.get(args.event)
    if handler:
        handler(cfg, stdin_data)


if __name__ == "__main__":
    main()

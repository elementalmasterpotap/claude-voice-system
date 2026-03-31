#!/usr/bin/env python3
"""
generate_voice_cache.py — прегенерация голосовых фраз через edge-tts.

Генерирует MP3 для всех стандартных фраз, кладёт в ~/.claude/sounds/cache/.
Также генерирует мягкие WAV тоны в ~/.claude/sounds/soft/.

Запуск: python generate_voice_cache.py [--voice ru-RU-DmitryNeural]
"""

import asyncio
import argparse
import math
import os
import struct
import wave
from pathlib import Path

CACHE_DIR = Path(os.path.expanduser("~/.claude/sounds/cache"))
SOFT_DIR = Path(os.path.expanduser("~/.claude/sounds/soft"))

# Фразы для прегенерации
PHRASES = {
    "editing":       "Редактирую",
    "writing":       "Записываю",
    "running":       "Запускаю",
    "reading":       "Читаю",
    "searching":     "Ищу",
    "searching_files": "Ищу файлы",
    "agent":         "Агент запущен",
    "fetching":      "Загружаю",
    "web_search":    "Ищу в сети",
    "skill":         "Загружаю скилл",
    "error":         "Ошибка",
    "waiting":       "Жду подтверждения",
    "session_start": "Привет, сессия запущена",
    "session_end":   "Сессия завершена",
    "compact":       "Сжимаю контекст",
    "compact_done":  "Контекст сжат",
    "done":          "Готово",
}

# Мягкие тоны (freq_hz, duration_ms, volume 0-1)
SOFT_TONES = {
    "soft_ping":  (800, 80, 0.3),
    "soft_low":   (400, 100, 0.25),
    "soft_high":  (1000, 50, 0.2),
}


def generate_soft_wav(name, freq, duration_ms, volume, sample_rate=44100):
    """Генерирует мягкий синусоидальный тон с fade in/out."""
    filepath = SOFT_DIR / f"{name}.wav"
    n_samples = int(sample_rate * duration_ms / 1000)
    fade_samples = min(int(sample_rate * 0.015), n_samples // 4)  # 15ms fade

    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        val = math.sin(2 * math.pi * freq * t) * volume

        # Fade in
        if i < fade_samples:
            val *= i / fade_samples
        # Fade out
        elif i > n_samples - fade_samples:
            val *= (n_samples - i) / fade_samples

        sample = int(val * 32767)
        sample = max(-32767, min(32767, sample))
        samples.append(struct.pack('<h', sample))

    with wave.open(str(filepath), 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b''.join(samples))

    print(f"  WAV: {name}.wav ({duration_ms}ms, {freq}Hz)")


async def generate_voice_phrases(voice):
    """Генерирует все голосовые фразы через edge-tts."""
    import edge_tts

    for name, text in PHRASES.items():
        filepath = CACHE_DIR / f"{name}.mp3"
        if filepath.exists():
            print(f"  SKIP: {name}.mp3 (уже есть)")
            continue
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice, rate="+15%")
            await communicate.save(str(filepath))
            size_kb = filepath.stat().st_size // 1024
            print(f"  MP3:  {name}.mp3 ({text}) [{size_kb}KB]")
        except Exception as e:
            print(f"  FAIL: {name}.mp3 — {e}")


PHRASES_PATH = Path(os.path.expanduser("~/.claude/sounds/phrases.json"))


async def sync_phrases_cache(voice):
    """Прегенерировать MP3 для всех фраз из phrases.json (base + learned)."""
    import edge_tts
    import hashlib

    if not PHRASES_PATH.exists():
        print("  phrases.json не найден")
        return

    import json
    with open(PHRASES_PATH, encoding="utf-8") as f:
        phrases = json.load(f)

    generated = 0
    skipped = 0
    for key, entry in phrases.items():
        if key.startswith("_"):
            continue
        all_phrases = list(entry.get("base", [])) + list(entry.get("learned", []))
        for text in all_phrases:
            h = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
            filepath = CACHE_DIR / f"auto_{h}.mp3"
            if filepath.exists():
                skipped += 1
                continue
            try:
                communicate = edge_tts.Communicate(text=text, voice=voice, rate="+15%")
                await communicate.save(str(filepath))
                size_kb = filepath.stat().st_size // 1024
                print(f"  MP3:  auto_{h}.mp3 ({text}) [{size_kb}KB]")
                generated += 1
            except Exception as e:
                print(f"  FAIL: {text} — {e}")

    # Сбросить счётчик learned_since_cache
    phrases.setdefault("_meta", {})["learned_since_cache"] = 0
    with open(PHRASES_PATH, "w", encoding="utf-8") as f:
        json.dump(phrases, f, indent=2, ensure_ascii=False)

    print(f"\n  Сгенерировано: {generated}, пропущено (уже есть): {skipped}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default="ru-RU-DmitryNeural",
                        help="Голос edge-tts (default: ru-RU-DmitryNeural)")
    parser.add_argument("--force", action="store_true",
                        help="Перегенерировать даже существующие файлы")
    parser.add_argument("--sync-phrases", action="store_true",
                        help="Прегенерировать кэш для всех фраз из phrases.json")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SOFT_DIR.mkdir(parents=True, exist_ok=True)

    if args.force:
        for f in CACHE_DIR.glob("*.mp3"):
            f.unlink()

    print(f"=== Генерация голосового кэша ({args.voice}) ===\n")

    # Мягкие WAV тоны
    print("Мягкие тоны:")
    for name, (freq, dur, vol) in SOFT_TONES.items():
        generate_soft_wav(name, freq, dur, vol)

    # Стандартные голосовые фразы
    print("\nГолосовые фразы (стандартные):")
    try:
        asyncio.run(generate_voice_phrases(args.voice))
    except Exception as e:
        print(f"\n⚠️ edge-tts недоступен ({e})")
        print("   Голосовые фразы не сгенерированы. Система будет использовать fallback.")

    # Синхронизация phrases.json → кэш
    if args.sync_phrases or True:  # всегда синхронизировать
        print("\nФразы из phrases.json:")
        try:
            asyncio.run(sync_phrases_cache(args.voice))
        except Exception as e:
            print(f"\n⚠️ sync-phrases ошибка ({e})")

    print("\n=== Готово ===")
    print(f"Кэш: {CACHE_DIR}")
    print(f"Тоны: {SOFT_DIR}")


if __name__ == "__main__":
    main()

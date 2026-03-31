<div align="center">

# Claude Voice System

**Self-learning neural voice for Claude Code**<br>
edge-tts · phrase pools · priority queue · anti-repeat

<br>

[![](https://img.shields.io/badge/v1.0.0-0099CC?style=flat-square)](https://github.com/elementalmasterpotap/claude-voice-system/releases)
[![](https://img.shields.io/badge/Windows-0078D6?style=flat-square&logo=windows&logoColor=white)](https://github.com/elementalmasterpotap/claude-voice-system)
[![](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![](https://img.shields.io/badge/edge--tts-FF7B00?style=flat-square)](https://github.com/rany2/edge-tts)
[![](https://img.shields.io/badge/license-MIT-22AA44?style=flat-square)](LICENSE)
[![](https://img.shields.io/badge/Telegram-channel-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://t.me/potap_attic)

</div>

---

<details>
<summary>English</summary>

**Neural voice notifications for Claude Code — free, self-learning, zero API keys.**

Tired of silence while Claude works? This system gives Claude a human voice. It speaks when tasks complete, errors occur, tools run, sessions start/end, and more.

## Features

| Feature | Description |
|---------|-------------|
| Neural TTS | Microsoft Edge-TTS (Dmitry/Svetlana voices), free, no API keys |
| 119 pre-generated phrases | Cached MP3, instant playback, no generation delay |
| Self-learning | Learns new phrases from Claude's responses automatically |
| Priority queue | Lock-file based — voices never overlap, no audio artifacts |
| Anti-repeat | Weighted random: less used phrases are more likely to play |
| 11 hook events | Stop, Notification, PreToolUse, SessionStart/End, Compact, and more |
| Tool-specific phrases | Different phrases for Edit, Bash, Read, Grep, Agent, etc. |
| Soft WAV fallback | If TTS unavailable — gentle sine-wave tones |
| `/voice` skill | Full control: on/off, male/female, volume, quiet hours, cache, test |

## Installation

```bash
git clone https://github.com/elementalmasterpotap/claude-voice-system
cd claude-voice-system
python install.py
```

The installer:
- Installs `edge-tts` via pip
- Copies scripts to `~/.claude/scripts/`
- Copies phrase dictionary to `~/.claude/sounds/`
- Generates soft WAV tones
- Registers 11 hooks in `settings.json`
- Creates `/voice` skill
- Pre-generates 119 MP3 phrase cache

## Usage

```
/voice              — show config
/voice on|off       — enable/disable
/voice male|female  — switch voice
/voice test         — play all events
/voice cache        — regenerate cache
/voice quiet 23:00-07:00 — quiet hours
```

## Uninstall

```bash
python install.py --remove
```

Removes hooks from `settings.json`. Scripts and cache left for manual cleanup.

## Architecture

```
Hook event
    |
    +- voice_enabled? -> pick phrase (weighted anti-repeat)
    |   +- cached MP3? -> play via WPF MediaPlayer
    |   +- no cache? -> edge-tts generate + auto-cache
    |       +- no internet? -> System.Speech fallback
    |
    +- sounds_enabled? -> soft WAV tone

Stop hook (special):
    +- learn_from_response() -> extract phrase from Claude's output
    +- speak summary or random phrase
```

## Requirements

- Windows 10/11
- Python 3.10+
- Claude Code CLI
- Internet (for first-time TTS generation, then cached)

</details>

<details open>
<summary>Русский</summary>

**Нейронный голос для Claude Code — бесплатно, с самообучением, без API-ключей.**

Надоела тишина пока Claude работает? Эта система даёт Claude человеческий голос. Он говорит когда задачи завершаются, возникают ошибки, запускаются инструменты, начинаются/заканчиваются сессии.

## Что умеет

| Фича | Описание |
|------|----------|
| Нейронный TTS | Microsoft Edge-TTS (Дмитрий/Светлана), бесплатно, без ключей |
| 119 прегенерированных фраз | Кэш MP3, мгновенное воспроизведение |
| Самообучение | Учит новые фразы из ответов Claude автоматически |
| Приоритетная очередь | Lock-файл — голоса не накладываются, нет артефактов |
| Антиповтор | Взвешенный рандом: реже используемые фразы — вероятнее |
| 11 событий хуков | Stop, Notification, PreToolUse, SessionStart/End, Compact и др. |
| Фразы по инструментам | Разные фразы для Edit, Bash, Read, Grep, Agent и т.д. |
| WAV fallback | Если TTS недоступен — мягкие синусоидальные тоны |
| Скилл `/voice` | Полное управление: вкл/выкл, голос, громкость, тихие часы, кэш, тест |

## Установка

```bash
git clone https://github.com/elementalmasterpotap/claude-voice-system
cd claude-voice-system
python install.py
```

Установщик:
- Ставит `edge-tts` через pip
- Копирует скрипты в `~/.claude/scripts/`
- Копирует словарь фраз в `~/.claude/sounds/`
- Генерирует мягкие WAV тоны
- Регистрирует 11 хуков в `settings.json`
- Создаёт скилл `/voice`
- Прегенерирует кэш из 119 MP3 фраз

## Использование

```
/voice              — показать конфиг
/voice on|off       — включить/выключить
/voice male|female  — сменить голос
/voice test         — проиграть все события
/voice cache        — перегенерировать кэш
/voice quiet 23:00-07:00 — тихие часы
```

## Удаление

```bash
python install.py --remove
```

Удаляет хуки из `settings.json`. Скрипты и кэш остаются для ручной очистки.

## Архитектура

```
Событие хука
    |
    +- voice_enabled? -> выбрать фразу (взвешенный антиповтор)
    |   +- кэш MP3? -> играть через WPF MediaPlayer
    |   +- нет кэша? -> edge-tts генерация + автокэш
    |       +- нет интернета? -> System.Speech fallback
    |
    +- sounds_enabled? -> мягкий WAV тон

Stop хук (особый):
    +- learn_from_response() -> извлечь фразу из ответа Claude
    +- озвучить summary или случайную фразу
```

## Структура phrases.json

```json
{
  "stop": {
    "base": ["Готово", "Сделано", "Збс, готово", ...],
    "learned": [],
    "stats": {"Готово": 3, "Сделано": 1}
  },
  "error": {
    "base": ["Ошибка", "Сломалось", "Крит-фейл", ...],
    "learned": [],
    "stats": {}
  }
}
```

- **base** — несъёмные стартовые фразы (сленг, живой язык)
- **learned** — выученные из ответов Claude (FIFO, макс 30)
- **stats** — счётчик использований (антиповтор: `1/(count+1)`)

## Требования

- Windows 10/11
- Python 3.10+
- Claude Code CLI
- Интернет (для первой генерации TTS, потом из кэша)

</details>

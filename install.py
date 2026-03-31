#!/usr/bin/env python3
"""
install.py — Claude Voice System installer.

Usage:
    python install.py           # Install
    python install.py --remove  # Uninstall
"""

import json
import math
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

CLAUDE_DIR = Path(os.path.expanduser("~/.claude"))
SCRIPTS_DIR = CLAUDE_DIR / "scripts"
SOUNDS_DIR = CLAUDE_DIR / "sounds"
CACHE_DIR = SOUNDS_DIR / "cache"
SOFT_DIR = SOUNDS_DIR / "soft"
CONFIG_PATH = CLAUDE_DIR / "sound_config.json"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"
SKILL_DIR = CLAUDE_DIR / "skills" / "sound-config"
SRC_DIR = Path(__file__).parent / "src"

VOICE_SCRIPT = "voice_system.py"
CACHE_SCRIPT = "generate_voice_cache.py"
PHRASES_FILE = "phrases.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "voice_enabled": True,
    "sounds_enabled": True,
    "voice_name": "ru-RU-DmitryNeural",
    "voice_rate": "+15%",
    "volume": "high",
    "quiet_hours": None,
}

# 11 hook events → voice_system.py
HOOK_EVENTS = [
    ("Stop", None),
    ("Notification", None),
    ("PreToolUse", None),
    ("PostToolUse", None),
    ("PostToolUseFailure", None),
    ("SessionStart", None),
    ("SessionEnd", None),
    ("PreCompact", None),
    ("PostCompact", None),
    ("SubagentStart", None),
    ("UserPromptSubmit", None),
]

SKILL_MD = """---
name: voice-config
description: "Manage Claude Code voice system: voice, sounds, TTS, test"
user-invocable: true
---

# /voice — voice system control

## Commands

```
/voice              — show current config
/voice on           — enable all
/voice off          — disable all
/voice voice on|off — toggle voice (soft WAV stays)
/voice sounds on|off — toggle soft WAV
/voice volume high|medium|low|mute
/voice male         — male voice (DmitryNeural)
/voice female       — female voice (SvetlanaNeural)
/voice cache        — pre-generate phrase cache
/voice test         — play ALL events
/voice quiet HH:MM-HH:MM — quiet hours
/voice quiet off    — disable quiet hours
```

## Implementation

Config: `~/.claude/sound_config.json`
Script: `~/.claude/scripts/voice_system.py`
Cache: `~/.claude/sounds/cache/` (MP3 phrases)
Tones: `~/.claude/sounds/soft/` (soft WAV)

### /voice (no args)

Show config as pseudographic tree.

### /voice cache

```bash
python ~/.claude/scripts/generate_voice_cache.py
```

### /voice test

```bash
python ~/.claude/scripts/voice_system.py --test
```

### Config changes

```python
import json, os
path = os.path.expanduser('~/.claude/sound_config.json')
with open(path, encoding='utf-8') as f:
    cfg = json.load(f)
# cfg["voice_enabled"] = True/False
# cfg["voice_name"] = "ru-RU-DmitryNeural" / "ru-RU-SvetlanaNeural"
with open(path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
```
"""


def log(msg):
    print(f"  {msg}")


def generate_soft_wav(name, freq, duration_ms, volume, sample_rate=44100):
    """Generate a soft sine-wave tone with fade in/out."""
    filepath = SOFT_DIR / f"{name}.wav"
    if filepath.exists():
        return
    n_samples = int(sample_rate * duration_ms / 1000)
    fade_samples = min(int(sample_rate * 0.015), n_samples // 4)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        val = math.sin(2 * math.pi * freq * t) * volume
        if i < fade_samples:
            val *= i / fade_samples
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
    log(f"WAV: {name}.wav ({duration_ms}ms, {freq}Hz)")


def install_edge_tts():
    """Install edge-tts if not present."""
    try:
        import edge_tts  # noqa: F401
        log("edge-tts: already installed")
        return True
    except ImportError:
        pass
    log("Installing edge-tts...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "edge-tts"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        log("edge-tts: installed")
        return True
    else:
        log(f"edge-tts: install failed — {result.stderr.strip()}")
        return False


def copy_scripts():
    """Copy voice_system.py and generate_voice_cache.py to ~/.claude/scripts/."""
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    for fname in [VOICE_SCRIPT, CACHE_SCRIPT]:
        src = SRC_DIR / fname
        dst = SCRIPTS_DIR / fname
        if src.exists():
            shutil.copy2(src, dst)
            log(f"Copied: {fname} -> {dst}")
        else:
            log(f"WARNING: {src} not found")


def copy_phrases():
    """Copy phrases.json to ~/.claude/sounds/ (only if not exists — preserve user's learned phrases)."""
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    dst = SOUNDS_DIR / PHRASES_FILE
    if dst.exists():
        log("phrases.json: already exists (preserving learned phrases)")
        return
    src = SRC_DIR / PHRASES_FILE
    if src.exists():
        shutil.copy2(src, dst)
        log(f"Copied: {PHRASES_FILE} -> {dst}")


def create_dirs():
    """Create cache and soft directories."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SOFT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Directories: {CACHE_DIR}, {SOFT_DIR}")


def generate_soft_tones():
    """Generate soft WAV tones."""
    tones = {
        "soft_ping": (800, 80, 0.3),
        "soft_low":  (400, 100, 0.25),
        "soft_high": (1000, 50, 0.2),
    }
    for name, (freq, dur, vol) in tones.items():
        generate_soft_wav(name, freq, dur, vol)


def create_config():
    """Create sound_config.json if not exists."""
    if CONFIG_PATH.exists():
        log("sound_config.json: already exists")
        return
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
    log("Created: sound_config.json")


def create_skill():
    """Create /voice skill if not exists."""
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    skill_path = SKILL_DIR / "SKILL.md"
    if skill_path.exists():
        log("Skill /voice: already exists")
        return
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(SKILL_MD.strip() + "\n")
    log("Created: skill /voice")


def _voice_cmd():
    """Build the hook command string."""
    script = str(SCRIPTS_DIR / VOICE_SCRIPT).replace("\\", "/")
    return f"python \"{script}\" --event $CLAUDE_EVENT"


def register_hooks():
    """Register voice hooks in settings.json."""
    if not SETTINGS_PATH.exists():
        log("WARNING: settings.json not found — create it first")
        return

    with open(SETTINGS_PATH, encoding="utf-8") as f:
        settings = json.load(f)

    hooks = settings.setdefault("hooks", {})
    cmd = _voice_cmd()
    marker = "voice_system.py"
    registered = 0

    for event, _ in HOOK_EVENTS:
        event_hooks = hooks.setdefault(event, [])
        # Check if already registered (search in nested hooks too)
        already = False
        for entry in event_hooks:
            if isinstance(entry, dict):
                # Check flat format
                if marker in str(entry.get("command", "")):
                    already = True
                    break
                # Check nested format (matcher + hooks[])
                for h in entry.get("hooks", []):
                    if marker in str(h.get("command", "")):
                        already = True
                        break
            if already:
                break
        if already:
            continue
        hook_entry = {
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": cmd.replace("$CLAUDE_EVENT", event),
            }],
        }
        event_hooks.append(hook_entry)
        registered += 1

    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

    log(f"Hooks: {registered} registered ({len(HOOK_EVENTS)} total events)")


def run_cache_generation():
    """Run generate_voice_cache.py to pre-generate MP3 phrases."""
    script = SCRIPTS_DIR / CACHE_SCRIPT
    if not script.exists():
        log("WARNING: generate_voice_cache.py not found, skipping cache generation")
        return
    log("Generating voice cache (this may take a minute)...")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        mp3_count = len(list(CACHE_DIR.glob("*.mp3")))
        log(f"Cache: {mp3_count} MP3 files generated")
    else:
        log(f"Cache generation had issues: {result.stderr[:200]}")


def install():
    """Full installation."""
    print("\n=== Claude Voice System — Install ===\n")

    # 1. edge-tts
    install_edge_tts()

    # 2. Copy scripts
    copy_scripts()

    # 3. Copy phrases.json
    copy_phrases()

    # 4. Create directories
    create_dirs()

    # 5. Generate soft WAV tones
    generate_soft_tones()

    # 6. Create config
    create_config()

    # 7. Create /voice skill
    create_skill()

    # 8. Register hooks
    register_hooks()

    # 9. Generate voice cache
    run_cache_generation()

    print("\n=== Done! ===")
    print(f"  Config:  {CONFIG_PATH}")
    print(f"  Scripts: {SCRIPTS_DIR}")
    print(f"  Cache:   {CACHE_DIR}")
    print(f"  Skill:   /voice")
    print("\n  Test: python ~/.claude/scripts/voice_system.py --test")
    print("  Control: /voice on|off|test|cache|male|female\n")


def remove():
    """Remove voice hooks from settings.json. Scripts left in place (manual cleanup)."""
    print("\n=== Claude Voice System — Remove ===\n")

    if not SETTINGS_PATH.exists():
        log("settings.json not found — nothing to remove")
        return

    with open(SETTINGS_PATH, encoding="utf-8") as f:
        settings = json.load(f)

    hooks = settings.get("hooks", {})
    marker = "voice_system.py"
    removed = 0

    for event in list(hooks.keys()):
        event_hooks = hooks[event]
        before = len(event_hooks)
        filtered = []
        for entry in event_hooks:
            # Check nested format (matcher + hooks[])
            nested_hooks = entry.get("hooks", [])
            if nested_hooks:
                has_voice = any(marker in str(h.get("command", "")) for h in nested_hooks)
                if has_voice:
                    continue
            # Check flat format
            elif marker in str(entry.get("command", "")):
                continue
            filtered.append(entry)
        hooks[event] = filtered
        removed += before - len(hooks[event])
        if not hooks[event]:
            del hooks[event]

    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

    log(f"Removed {removed} hooks from settings.json")
    log("Scripts and cache left in place. To fully remove:")
    log(f"  rm {SCRIPTS_DIR / VOICE_SCRIPT}")
    log(f"  rm {SCRIPTS_DIR / CACHE_SCRIPT}")
    log(f"  rm -rf {CACHE_DIR}")
    log(f"  rm -rf {SOFT_DIR}")
    log(f"  rm {CONFIG_PATH}")

    print("\n=== Done! ===\n")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        install()

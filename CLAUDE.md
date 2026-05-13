# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands assume the repo-local venv at `.venv/`. On Windows use `.\.venv\Scripts\python.exe`; in bash (Git Bash / MSYS) use `./.venv/Scripts/python.exe`.

- Install deps: `./.venv/Scripts/python.exe -m pip install -r requirements.txt`
- Run the app: `./.venv/Scripts/python.exe main.py`
- Preview only the pet window (no controller/threads): `./.venv/Scripts/python.exe ui_core.py`
- Syntax check (no test suite exists): `./.venv/Scripts/python.exe -m py_compile main.py ui_core.py chat_thread.py observer_thread.py llm_client.py config_loader.py pet_state.py logging_utils.py`
- Validate animation frames (24+ frames/state, transparency, drift): `./.venv/Scripts/python.exe tools/validate_pet_frames.py`
- Rebuild animation frames from `assets/source/*_source.png`: `./.venv/Scripts/python.exe tools/rebuild_pet_actions.py` (add `--clarity 0` to disable sharpening, `--with-webp-frames` to also emit WebP)
- Generate preview sheet: `./.venv/Scripts/python.exe tools/preview_pet_frames.py`
- Build Windows `.exe`: `./.venv/Scripts/python.exe tools/build_exe.py` (wraps PyInstaller; output to `dist/CodingPet.exe`)

There is no linter, formatter, or test runner configured. `codingpet.log` is written alongside the working directory during source runs, and under `%APPDATA%\CodingPet\` when frozen.

## Architecture

CodingPet is a PyQt6 desktop pet that talks to an OpenAI-compatible Chat Completions endpoint. The app is a single process with three cooperating pieces: the UI (main thread), a one-shot chat worker thread, and an optional polling observer thread. All cross-thread communication goes through Qt signals — never call UI methods directly from workers.

### Control flow

[main.py](main.py) — `CodingPetController` is the central hub. It owns `PetWindow` (UI), the active `ChatWorker` (at most one in flight), and the optional `ObserverWorker`. It enforces the single-request invariant in `_start_chat`, pauses random-mood scheduling during interactions, and reloads config in `_apply_config` which also restarts the observer thread. State lifecycle: `IDLE` → user/observer event sets a state → `_state_reset_timer` returns to `IDLE` after `runtime.state_reset_ms`. Manual drags/resizes set `_manual_override_active` to suppress the random-mood timer until the interaction ends.

[chat_thread.py](chat_thread.py) — `ChatWorker` is a `QThread` that captures a screenshot (only if `observer.global_observation_enabled` is true — the same flag gates both active-chat screenshots and the passive observer), calls `generate_chat_reply`, and emits `response_ready(user_text, message, emotion)` or `request_failed`.

[observer_thread.py](observer_thread.py) — `ObserverWorker` polls the foreground window via `pygetwindow`, grabs just that window's region (falls back to full screen if geometry is missing), and calls `analyze_screenshot`. It uses a flag-based cooperative stop (`stop()` + chunked `msleep`) — do not replace with `terminate()`; in-flight HTTP requests must be allowed to return.

[llm_client.py](llm_client.py) — Model selection hinges on whether a screenshot is attached: `vision_model_name` if yes, `chat_model_name` if no. `generate_chat_reply` auto-downgrades to text-only on `BadRequestError`/`NotFoundError` matching vision-unsupported keywords; `analyze_screenshot` does not (the observer's whole job is vision). Multi-turn history is only sent when `chat.multi_turn_enabled` is true, truncated to the last `chat.memory_turns` turns.

### The `[STATE] message` reply protocol

Both system prompts instruct the model to emit exactly `[STATE] text` on one line. `parse_model_reply` in [llm_client.py](llm_client.py) tries the strict regex first, falls back to JSON (`{message, emotion}` or `{reply, sentiment}`, etc.), and ultimately returns `PetState.IDLE` with the raw text. `PetState.from_emotion` in [pet_state.py](pet_state.py) maps synonyms (e.g. `ROAST`→`ANGRY`, `TIRED`→`SLEEPY`) — extend this mapping rather than tightening the prompt when models drift. Valid state tokens must match `PetState` enum names; `STATE_NAMES` in llm_client is built from the enum, so adding a state there (plus the `assets/<state>/` directory and an entry in `STATE_ANIMATION_FRAME_MS` in [ui_core.py](ui_core.py)) is all that's needed to support it end-to-end.

### Configuration resolution

[config_loader.py](config_loader.py) handles a dual source/frozen runtime. When running from source, `config.yaml` is read from the project dir. When frozen (PyInstaller), the default config path redirects to `%APPDATA%\CodingPet\config.yaml`, and on first launch the bundled `config.example.yaml` is copied there. `resource_path()` resolves assets through `sys._MEIPASS` when frozen. Any code that needs a file path should go through `application_dir()`, `user_config_dir()`, or `resource_path()` — do not compute paths relative to `__file__` directly.

`AppConfig` is a frozen dataclass tree (`LLMConfig`, `PetPresetConfig`, `ChatConfig`, `ObserverConfig`, `RuntimeConfig`). `CoreSettings` is the flattened subset editable in [settings_dialog.py](settings_dialog.py); `save_core_settings` preserves unexposed fields by reading and rewriting the YAML. `load_config` enforces minimum values (observer interval ≥ 5s, request timeout ≥ 5s, memory turns clamped to 1–20) — respect these when adding new numeric config.

### Conversation history

[conversation_history.py](conversation_history.py) — `ChatTurn` is in-memory only; nothing persists across runs. The `source` field distinguishes `ACTIVE_CHAT_SOURCE` (user-initiated) from `PASSIVE_CHAT_SOURCE` (observer-initiated); [context_dialog.py](context_dialog.py) renders them differently. When adding new turn sources, update both the dialog rendering and `_active_chat_history` filtering in llm_client if they should be sent back to the model.

### UI specifics

[ui_core.py](ui_core.py) is a frameless, always-on-top, transparent `QWidget`. On Windows it calls `DwmSetWindowAttribute` to kill the residual DWM border (see `_remove_system_window_outline`). Per-state frame intervals live in `STATE_ANIMATION_FRAME_MS`. Resize zones are edge/corner hit-tests with `RESIZE_MARGIN=10`; right-click is either a menu (short press) or resize (drag past `RIGHT_CLICK_DRAG_THRESHOLD`).

## Conventions

- Comments throughout the codebase are in Chinese; match the surrounding style when editing.
- Module-level docstrings are absent by design — short Chinese inline comments explain *why*, not *what*.
- `from __future__ import annotations` is used everywhere; keep it when adding new modules.
- Never block the UI thread with network or screen capture — always route through a `QThread` worker and Qt signals.

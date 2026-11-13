# Switch Bot 🎥🤖

**Real-time, AI-assisted multi-camera production orchestrator.**
Switch Bot watches and listens to a live production, decides which camera to cut to, drives the hardware and software switchers, and writes an edit-ready timeline (EDL + DaVinci Resolve project) with smart markers while the show is still running.

Started at a [Código Facilito](https://codigofacilito.com) hackathon and grown into a full system for live productions.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white)
![MediaPipe](https://img.shields.io/badge/Vision-MediaPipe-0097A7)
![AWS Bedrock](https://img.shields.io/badge/AI-AWS%20Bedrock%20%7C%20Ollama-FF9900?logo=amazonaws&logoColor=white)
![Tests](https://img.shields.io/badge/tests-pytest%20%2B%20Hypothesis-6E40C9)

> 🇬🇹 **Resumen en español:** Switch Bot es un orquestador de producción multicámara en tiempo real. Usa visión por computadora (MediaPipe) y detección de voz para decidir los cortes de cámara, controla un switcher Blackmagic ATEM y OBS Studio, compara lo que se dice en vivo contra el guion con IA (AWS Bedrock u Ollama local) y genera al mismo tiempo un EDL (CMX 3600) y un proyecto de DaVinci Resolve con marcadores de color listos para postproducción.

---

## ✨ What it does

| | Feature | Details |
|---|---|---|
| 🎯 | **Automatic camera switching** | MediaPipe gaze tracking + voice activity detection feed a decision engine that picks the best camera. A hysteresis filter enforces a minimum cooldown (90 frames ≈ 3 s at 30 fps) so cuts never feel erratic. |
| 🎛️ | **Hardware + software switching** | Sends asynchronous TCP commands to a **Blackmagic ATEM** switcher (PyAtemMax) and mirrors the program output in **OBS Studio** over WebSocket. |
| 📜 | **Script-aware AI** | Loads a script (PDF, Markdown, or JSON), vectorizes it as a RAG base, and compares each spoken segment against the expected block. Segments with similarity below 0.7 get a `SCRIPT_DEVIATION` marker with the expected vs. detected text. |
| 🔀 | **Pluggable AI backends** | **AWS Bedrock** (Titan Embeddings V2 + Claude) in the cloud, or **local models** (Ollama / llama.cpp / GGUF) on the operator's machine. If the backend fails, the session keeps running and the failure is logged with its timecode. |
| 🗣️ | **Vocal anomaly markers** | Flags coughs, mispronunciations, confusions, and repetitions as red markers so the editor finds them instantly in post. |
| 🎞️ | **Edit-ready output, live** | Writes a **CMX 3600 EDL** and a **DaVinci Resolve (.drp)** project incrementally, with color-coded markers by source (manual, AI, anomaly). Both serializers are round-trip tested. |
| 🛑 | **Human in control** | A panic button pauses automation or injects emergency flags. Manual notes and AI prompts bypass the cooldown and land on the exact SMPTE timecode. |
| 📣 | **Post-session suggestions** | Generates ad/clip suggestions from the session once it ends. |

### Example output

A few events from a real session EDL (markers come from the live operator and from the AI):

```text
TITLE: TEMA 10 - CREES ESTO
FCM: NON-DROP FRAME

001  001      V     C        10:42:04:03 10:42:04:04 10:42:04:03 10:42:04:04
 |C:ResolveColorCyan |M:ENTRADA |D:1

003  001      V     C        10:42:18:12 10:42:18:13 10:42:18:12 10:42:18:13
 |C:ResolveColorGreen |M:IMAGEN |D:1
```

---

## 🏗️ Architecture

```text
 ┌───────────── Capture ─────────────┐     ┌──────── Inference ────────┐
 │ 4 video feeds + PCM audio          │ ──▶ │ MediaPipe gaze tracking    │
 │ (60 / 30 / 29.97 fps)              │     │ Voice activity detection   │
 └────────────────────────────────────┘     └─────────────┬──────────────┘
                                                          ▼
 ┌──────── Script + AI ────────┐   ┌──────── Decision engine ─────────┐
 │ Script parser (PDF/MD/JSON) │──▶│ Camera choice + hysteresis filter │◀── Panic button / manual notes
 │ IA enricher: Bedrock|Ollama │   └─────────────────┬─────────────────┘
 └─────────────────────────────┘                     ▼
                         ┌──────────────── Dispatcher ────────────────┐
                         │  ATEM pipeline │ OBS pipeline │ EDL │ DRP   │
                         └─────────────────────────────────────────────┘
```

- Capture, inference, and execution run in **isolated processes** connected by `multiprocessing.Queue`, so a slow AI call or file write never blocks video capture.
- Timecodes are **SMPTE (HH:MM:SS:FF)** aligned to time of day.
- A detailed visual diagram lives in [`docs/architecture.html`](docs/architecture.html).

### Project layout

```text
switch_bot/
├── capture/       # multi-feed video + audio capture
├── inference/     # MediaPipe inference engine
├── engines/       # decision engine, hysteresis, panic button, script parser, vocal anomalies
├── ia/            # AI enricher + Bedrock / local backends, model catalog
├── pipelines/     # ATEM, OBS, EDL, metadata (.jsonl + .drp), dispatcher
├── serializers/   # CMX 3600 EDL and DaVinci Resolve DRP serializers
├── gui/           # PyQt6 operator console (themes, Bedrock/local model panels)
├── web/           # hybrid client-server mode (in progress, see roadmap)
└── coordinator.py # wires everything together
tests/             # unit, property-based (Hypothesis), GUI and integration tests
```

---

## 🚀 Getting started

**Requirements:** Python 3.11+. For live switching you also need a Blackmagic ATEM on the network and/or OBS Studio with WebSocket enabled. For AI features, AWS credentials with Bedrock access **or** a local [Ollama](https://ollama.com) install.

```bash
git clone https://github.com/eduardo-zepeda-j/switch_bot.git
cd switch_bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python run_gui.py      # launch the operator console
pytest                 # run the test suite
```

> AWS credentials are never stored in the repo. The GUI keeps them in local settings (obfuscated, not encrypted), so protect your user profile.

---

## 🧪 Testing

The project was built spec-first (requirements → design → tasks, see [`.kiro/specs`](.kiro/specs)) and the test suite mirrors those specs:

- **Unit tests** for models, timecodes, payloads, and the agent client.
- **Property-based tests** with [Hypothesis](https://hypothesis.readthedocs.io) for the EDL/DRP round trips, hysteresis, dispatcher, panic button, script parser, and backend resilience.
- **GUI** and **end-to-end integration** tests.

---

## 🗺️ Roadmap

- [x] Real-time capture, inference, and decision engine
- [x] ATEM + OBS switching, EDL and DRP generation
- [x] AWS Bedrock and local (Ollama) AI backends
- [x] PyQt6 operator console redesign
- [ ] **Hybrid web architecture on AWS EC2**: a central server (coordination, Bedrock, EDL/metadata) plus a lightweight local agent (capture, MediaPipe, ATEM), linked by WebSocket with heartbeat, offline fallback mode, and state sync on reconnect. The WebSocket hub, agent client, AI router, heartbeat, fallback, and state sync modules exist; authentication tests and the web front end are pending.

---

## 👤 Author

**Eduardo Zepeda**: IT infrastructure & multimedia consultant, full-stack developer.
🌐 [Portfolio](https://eduardo-zepeda-j.github.io) · 💼 [LinkedIn](https://www.linkedin.com/in/eduardo-zepeda-j) · ▶️ [YouTube](https://www.youtube.com/@eduardozepeda1113)

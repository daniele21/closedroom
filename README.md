<p align="center">
  <img src="public/logo-light.svg" width="128" alt="ClosedRoom logo">
</p>

<h1 align="center">ClosedRoom</h1>

<p align="center">
  <strong>Private meeting intelligence for macOS.</strong><br>
  Record, transcribe, understand, and remember meetings with Local AI as the default boundary.
</p>

<p align="center">
  ClosedRoom turns meeting audio into <strong>speaker-aware transcripts, actions, decisions, risks, editable notes, and project memory</strong> without making cloud APIs the default home for sensitive meeting data.
</p>

<p align="center">
  <a href="https://github.com/daniele21/closedroom/actions/workflows/repository-health.yml"><img alt="Repository health" src="https://github.com/daniele21/closedroom/actions/workflows/repository-health.yml/badge.svg?branch=main"></a>
  <img alt="macOS" src="https://img.shields.io/badge/macOS-Apple%20Silicon-000000?logo=apple&logoColor=white">
  <img alt="Local first" src="https://img.shields.io/badge/Local--first-default-0F766E">
  <img alt="Active development" src="https://img.shields.io/badge/status-active%20development-2563EB">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
</p>

<p align="center">
  <a href="#what-closedroom-does">Features</a> ·
  <a href="#how-you-use-it">How to use it</a> ·
  <a href="#run-closedroom">Run it</a> ·
  <a href="#local-first-by-default">Privacy model</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="docs/features.md">Feature registry</a> ·
  <a href="https://daniele21.github.io/">Mission</a>
</p>

<table>
<tr>
<td align="center">

### 🖼️ IMAGE PLACEHOLDER — HERO PRODUCT DEMO

**Target asset:** 20–30 second looping GIF or short video.

**What it should show:**  
`New Meeting → Record microphone + system audio → Stop → Local transcription → Prepare notes → Review actions/decisions → Project memory`

Use the real macOS application, one synthetic meeting, readable UI and no debug overlays. The viewer should understand in a few seconds that ClosedRoom is **more than transcription: it converts a meeting into reusable operational memory**.

</td>
</tr>
</table>

## What ClosedRoom does

Most meeting tools stop at a transcript or send the meeting to a remote service by default. ClosedRoom is built around a different product idea:

> **A meeting should become useful memory, while the default trust boundary stays on your Mac.**

### Core product capabilities

| Capability | What you get |
| --- | --- |
| **Local meeting capture** | Record microphone and system audio on macOS, preserve recoverable artifacts, and save the meeting before expensive inference starts. |
| **Local transcription** | Transcribe on-device with MLX Whisper or Nemotron ASR, with persisted jobs and reusable results. |
| **Speaker-aware transcripts** | Separate speakers locally with FluidAudio and keep speaker clusters stable across review and recalculation. |
| **Structured meeting intelligence** | Turn a transcript into summaries, actions, decisions, risks, open questions and meeting notes through a structured analysis pipeline. |
| **Verifiable, editable notes** | Review generated actions and decisions against source context, correct them, and preserve user edits across reloads and regenerated revisions. |
| **Project memory** | Reuse meeting outputs across a project so decisions, risks, commitments and updates do not disappear inside isolated transcripts. |

ClosedRoom can also add optional enrichment without making the core workflow depend on it: conservative visual speaker attribution, richer diagnostics, provider alternatives and deeper analysis paths.

## From meeting to operational memory

The main product flow is deliberately simple:

```text
New Meeting
    │
    ▼
Record locally
    │
    ▼
Save the meeting first
    │
    ▼
Transcribe
    │
    ▼
Enrich speakers / context
    │
    ▼
Prepare structured notes
    │
    ▼
Review and edit
    │
    ▼
Reuse in Today / Project memory
```

<table>
<tr>
<td align="center">

### 🖼️ IMAGE PLACEHOLDER — MEETING → MEMORY PRODUCT JOURNEY

**Target asset:** horizontal 6-frame walkthrough built from real ClosedRoom screens.

**Required sequence:**  
`New Meeting → Recording → Transcript → Prepare notes → Review / edit → Project memory`

Use the same synthetic meeting throughout. Make the transformation visually obvious: **audio becomes transcript; transcript becomes decisions and actions; those outputs become reusable project context**.

</td>
</tr>
</table>

## See the product

<table>
  <tr>
    <th>Today</th>
    <th>Recording</th>
    <th>Meeting intelligence</th>
  </tr>
  <tr>
    <td align="center"><a href="docs/assets/0.home.png"><img src="docs/assets/0.home.png" width="240" alt="ClosedRoom Today workspace"></a></td>
    <td align="center"><a href="docs/assets/1.recording.png"><img src="docs/assets/1.recording.png" width="240" alt="ClosedRoom recording setup"></a></td>
    <td align="center"><a href="docs/assets/5.meeting-analysis.png"><img src="docs/assets/5.meeting-analysis.png" width="240" alt="ClosedRoom meeting intelligence workspace"></a></td>
  </tr>
  <tr>
    <td align="center">Meetings, actions, decisions, risks and context</td>
    <td align="center">A focused capture flow with optional advanced controls</td>
    <td align="center">Transcript, speakers, sources and structured analysis</td>
  </tr>
</table>

<table>
  <tr>
    <th>Project memory</th>
    <th>Deep-dive actions</th>
  </tr>
  <tr>
    <td align="center"><a href="docs/assets/6.project-analysis.png"><img src="docs/assets/6.project-analysis.png" width="320" alt="ClosedRoom project memory workspace"></a></td>
    <td align="center"><a href="docs/assets/4.deep-dive-actions.png"><img src="docs/assets/4.deep-dive-actions.png" width="320" alt="ClosedRoom deep-dive action items"></a></td>
  </tr>
  <tr>
    <td align="center">Cross-meeting status, decisions, risks and updates</td>
    <td align="center">Operational detail extracted from meeting intelligence</td>
  </tr>
</table>

## How you use it

A normal ClosedRoom workflow does not require choosing models, audio devices or inference parameters before every meeting.

1. **Start a new meeting.** Add a title or project if useful; both can remain lightweight.
2. **Grant the macOS permissions needed for capture.** ClosedRoom prefers native microphone + system-audio capture where supported.
3. **Record.** Audio is written progressively so the meeting can be recovered even if later processing fails.
4. **Stop the meeting.** ClosedRoom finalizes the recording before starting expensive AI work.
5. **Transcribe.** The default path uses local ASR; transcription runs as a persisted, observable job.
6. **Prepare notes.** ClosedRoom creates one structured meeting-intelligence result that feeds the main summary, action, decision and risk views.
7. **Review and edit.** Generated items remain human-reviewable; corrections are persisted instead of being silently replaced on refresh or regeneration.
8. **Reuse the result.** Today and Project workspaces surface context across meetings rather than treating each transcript as an isolated file.

Optional visual intelligence can be enabled for a specifically selected macOS window. It may contribute evidence for naming existing speaker clusters, but **audio diarization remains the source of who spoke when and uncertain identity mappings abstain rather than pretending certainty**.

<table>
<tr>
<td align="center">

### 🖼️ IMAGE PLACEHOLDER — SPEAKER INTELLIGENCE

**Target asset:** compact 3-stage technical/product visual.

**What it should show:**  
`Audio diarization → stable speaker clusters → optional visual evidence → conservative human-readable names`

The image must make the boundary clear: **visual intelligence does not replace diarization and does not turn uncertain evidence into a claimed identity**. Show an explicit “abstain / unknown” path when confidence is insufficient.

</td>
</tr>
</table>

## Local-first by default

ClosedRoom is **local-first, not local-only**.

The default product path keeps the sensitive meeting workflow on the Mac. Cloud providers exist as explicit choices, not silent fallbacks.

| Area | Default | Optional alternative |
| --- | --- | --- |
| Recording | Local macOS capture | — |
| Speech-to-text | Local MLX Whisper / Nemotron | Speechmatics when explicitly selected |
| Speaker diarization | Local FluidAudio on supported Macs | Speechmatics when explicitly selected |
| Meeting analysis | Local `local-llm-server` | Gemini when explicitly selected |
| Visual speaker evidence | Local selected-window frames + local VLM path | Disabled unless explicitly enabled |
| Persistence | Local filesystem + SQLite | No implicit remote persistence |

This is a product boundary, not a marketing label: provider selection, runtime ownership and failure states are explicit so a local failure does not silently move meeting content to a cloud API.

![ClosedRoom high-level local-first architecture](docs/assets/closedroom-high-level-architecture.png)

_The default trust boundary stays on the user's Mac; cloud providers sit outside it and are used only when explicitly selected._

## Architecture

ClosedRoom separates the **meeting product** from reusable local model runtime concerns.

```text
ClosedRoom macOS app / React workspace
              │
              ▼
     Loopback FastAPI boundary
              │
      ┌───────┼────────┐
      │       │        │
 Recording  Jobs   Local persistence
      │       │        │
      └───────┼────────┘
              │
     ┌────────┴─────────┐
     │                  │
 Local ASR / diarization   local-llm-server
     │                  │
 transcript + speakers   text / vision inference
     └──────────┬────────┘
                ▼
      Meeting / Project memory
```

The key ownership split is:

- **ClosedRoom owns the user problem:** capture, meetings, transcripts, speaker state, structured notes, user edits, project memory, persistence and product UX.
- **`local-llm-server` owns reusable local LLM/VLM runtime infrastructure:** model loading, backend selection, runtime lifecycle, inference modes, logs and diagnostics.
- **Native helpers own platform-specific capture and diarization work** behind explicit process boundaries.

![ClosedRoom detailed technical architecture](docs/assets/closedroom-detailed-technical-architecture.png)

For durable ownership and extension rules, read [`docs/architecture.md`](docs/architecture.md).

## Designed to degrade usefully

Meeting intelligence is a pipeline, so one optional enrichment should not invalidate everything that came before it.

ClosedRoom therefore distinguishes the core meeting artifact from optional stages:

- a recording is finalized before transcription;
- a usable transcript can survive diarization or visual-intelligence degradation;
- visual speaker attribution can abstain;
- diagnostics record effective backends, warnings and failure causes;
- jobs are persistent, cancellable and recoverable where the workflow requires it;
- invalid or stale structured-note edits are surfaced as explicit conflicts instead of being silently remapped.

This is one of the main engineering goals of the project: **local AI should behave like a product system, not like a successful-demo-only pipeline**.

## Run ClosedRoom

### Current distribution

ClosedRoom is currently an **active-development, source-built macOS project**. A public downloadable GitHub Release is not published yet, so the supported path today is to run or build the project from source.

### Requirements

- macOS
- Apple Silicon recommended and required for some MLX / FluidAudio paths
- Python `>=3.10,<3.14`
- Homebrew for the repository setup script
- `ffmpeg`
- `uv` recommended
- local model storage appropriate for the ASR / LLM models you choose

Cloud credentials are **not required** for the default local path.

### Install and launch

```bash
git clone https://github.com/daniele21/closedroom.git
cd closedroom

./setup.sh
./run.sh
```

Then open:

```text
http://127.0.0.1:1236
```

The repository still uses the internal Python package / CLI name `local-asr-server` / `local-asr` for the local backend. That is an implementation boundary inside the **ClosedRoom** product, not a separate repository to clone.

### Start the local API directly

```bash
local-asr serve \
  --model mlx-community/nemotron-3.5-asr-streaming-0.6b \
  --recordings-dir ~/Recordings/local-asr \
  --port 1236
```

For development with reload:

```bash
UV_CACHE_DIR=.cache/uv uv run local-asr serve --reload
```

### Build the native macOS application

```bash
./build.sh --no-dmg
```

The packaged application includes the native capture helper and FluidAudio diarization helper. Packaging and target-Mac behavior require the applicable macOS toolchain and real-environment validation.

## Current status and limits

ClosedRoom already implements the core meeting-intelligence workflow, but it remains under active development.

Current boundaries worth knowing:

- the product is focused on macOS, with the strongest local inference path on Apple Silicon;
- local FluidAudio diarization requires supported macOS / hardware and remains an enrichment rather than a prerequisite for transcription;
- visual intelligence is disabled by default and only observes a window explicitly selected by the user;
- automatic speaker naming is conservative and may intentionally leave a speaker unnamed;
- Speechmatics and Gemini are opt-in providers and move selected meeting data outside the local trust boundary;
- no public binary GitHub Release is available yet;
- model quality, latency, memory and thermal behavior should be treated as environment/model dependent unless backed by representative recorded evidence.

ClosedRoom is not a guarantee of perfect transcription, speaker identity or meeting understanding. Human review remains part of the product model.

## For developers

### Repository map

| Area | Main paths | Responsibility |
| --- | --- | --- |
| Product UI | `frontend/src/` | Today, recording, meeting, project, settings and guided workflows |
| API / composition | `src/local_asr_server/server.py`, `app_services.py` | FastAPI boundary, route wiring and long-lived services |
| Recording / capture | `recordings.py`, native helpers, `audio_router.py` | Progressive capture, recovery, macOS audio and optional visual frames |
| Transcription / diarization | `transcriptions.py`, `asr_provider.py`, `speaker_diarization_helper/` | ASR providers, transcript persistence and speaker clustering |
| Meeting intelligence | analysis jobs, templates, structured notes | Structured meeting outputs, source references, edits and revisions |
| Local model runtime | `local-llm-server` dependency + runtime manager | Local LLM/VLM lifecycle and inference |
| Persistence | `catalog.py`, settings and paths | SQLite catalog, artifacts, configuration and durable state |
| macOS app | `menubar.py`, `window.py`, `ClosedRoom.spec`, build scripts | WKWebView shell, menu bar, bundling and packaging |

Start with [`AGENTS.md`](AGENTS.md) for engineering ownership and [`docs/features.md`](docs/features.md) for the business/technical feature registry.

### Canonical development commands

```bash
# setup
./setup.sh
(cd frontend && pnpm install --frozen-lockfile)

# repository checks
python3 scripts/verify_repository.py

# tests
UV_CACHE_DIR=.cache/uv uv run python -m unittest discover -s test -v

# build
bash scripts/build_artifact.sh --no-dmg
```

Canonical commands and validation stages live in [`.engineering/commands.json`](.engineering/commands.json).

### Local API

The browser workspace, WKWebView shell and diagnostics use the same loopback API boundary.

```bash
curl -c /tmp/closedroom.cookies http://127.0.0.1:1236/v1/session
curl http://127.0.0.1:1236/health
```

For endpoint-level behavior, provider options, speaker recalculation, analysis pipelines and diagnostics, see [`docs/features.md`](docs/features.md) and [`docs/architecture.md`](docs/architecture.md).

## Contributing

ClosedRoom uses `dev → main` as its canonical branch flow. Ordinary feature and fix work branches from `dev` and returns to `dev` through a pull request; `main` is the stable promotion line.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development and validation model, and [`SECURITY.md`](SECURITY.md) for security reporting.

## Project context

ClosedRoom is part of [Daniele Moltisanti's Local AI work](https://daniele21.github.io/): build real products on top of reusable Local AI infrastructure, measure what works, and keep **Local, Hybrid and Cloud** as explicit architectural choices rather than accidental dependencies.

Its role in that mission is concrete: **prove that sensitive meeting workflows can become useful, persistent AI-assisted memory while keeping the default data boundary under the user's control.**

## License

ClosedRoom is available under the [MIT License](LICENSE).

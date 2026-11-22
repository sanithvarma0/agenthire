# AgentHire

**A voice assistant that hires people for you, from an electrician to an engineer.** You say who you need. It finds real people, phones them in their own language, and brings back a shortlist with their own words as proof. You decide; it books.

Built solo at Builders 2026 (OpenAI x Equal AI), Hyderabad, 21–22 Nov 2026, in the Build Creative track.

**Live demo:** https://3-213-208-226.sslip.io (test mode: every call rings the builder). **Code:** https://github.com/sanithvarma0/agenthire. **Run it yourself:** [AGENTS.md](AGENTS.md). **Evidence of results, and what is built, reused and simulated:** [docs/SUBMISSION.md](docs/SUBMISSION.md).

## What it does

**At home: "my kitchen tap is leaking".**

1. **Brief.** You talk to the assistant in Telugu, Hindi or English (or a mix). A real-time avatar listens and asks what a plumber would need to know, then reads back a one-line summary for your OK.
2. **Find.** Real plumbers near your location from Google Places, ranked by distance, rating and reviews, shown on a night map.
3. **Call.** One tap, and it phones the top two, one at a time, in everyday Telugu or Hindi. It sounds like a neighbour calling about a problem at home, and asks when they can come and what they charge. You watch the live transcript, and can tap **Listen live** to hear both voices as the call happens.
4. **Compare.** Who can come, when, for how much, each quoted from the call, with one recommendation.
5. **Book.** You pick one. It calls back to confirm the time and texts them your address.

**At work: "we need a data engineer".**

1. **Role brief.** HR describes the role by voice or typing. The assistant writes the job description, five screening questions in priority order, and a scoring guide for each. HR edits and approves.
2. **Candidates.** It crawls the web for public profiles that fit: name, headline, company, location and matching experience. It never takes phone numbers or emails.
3. **Screen.** HR ticks up to three candidates. An English screening call of up to 5 minutes asks the approved questions, understanding Hindi or Telugu mixed in. We never hold the candidates' numbers, so in this demo the call rings the builder, who answers as the candidate, and it is labelled that way everywhere.
4. **Shortlist.** Every answer is scored 1–5 against the approved guide. A score is shown only if the candidate's own words behind it are found in the transcript. Content only: never accent, fluency or grammar.

## Why it is AI-native

- **One conversation engine, driven by data.** Every conversation (the home brief, a call to a plumber, the booking call, the role brief, a screening call) is an entry in [`voice/kinds.yaml`](voice/kinds.yaml) written as requirements, never as scripted sentences. The model writes every line in the call's language. A test fails if the engine or the kinds file names a trade or a place, or contains scripted Hindi or Telugu.
- **The model decides; code guards.** gpt-5.5 holds each conversation through the Responses API, streamed so speech starts at the first clause. Code enforces only what must never go wrong:
  - who may be dialled (`can_dial`: approval, calling hours, do-not-call, 3 calls a job);
  - that a fact quotes the person's own words;
  - that a call cannot end before its outcome is known.
- **Grounded results.** After each call, a larger-model writer reads the whole transcript. A check in code then confirms every fact against the exact line it cites, and any number against the number said. Anything that fails is shown as "not confirmed", never as fact. Shortlist scores go through the same check.
- **Indian languages first.** Sarvam speech-to-text in code-mixed mode and Sarvam voices. Per-language style files teach everyday register, not textbook Telugu. Calls follow the person if they switch between Telugu and Hindi.

## Safety by default

- **Test mode is the demo toggle, and it is on unless switched off.** Providers are found for real, but every call and SMS goes to the builder's own phone (`DEMO_ROUTE_PHONE`), and results are labelled "answered by you". It is never remembered as the provider's own.
- **The test-mode switch** in the top bar is locked unless `TEST_MODE_PIN` is set in `.env`. The live server and the submission zip never have a PIN, so they always stay in test mode.
- Only `place_call` dials, and only through `can_dial`. Only `backend/messages.py` sends messages, and only through `can_message`.
- Nothing is dialled without the user's tap, and nobody found by the web crawl is ever contacted.
- The agent never claims to be human. If sincerely asked, it says it is an AI.

## How it is built

| Part | Choice |
|---|---|
| Voice | LiveKit Agents 1.8 worker, Twilio SIP for real phone calls, Sarvam STT (`saaras:v4`, code-mixed) and TTS (`bulbul`), noise cancellation |
| Models | OpenAI `gpt-5.5`: conversations (Responses API, streamed, reasoning low), brief, posting, result, comparison and scoring writers; web search tool for the candidate crawl |
| Avatar | Synthesia real-time avatar (LiveKit plugin), lip-synced to our own Sarvam voice; an orb if it does not start |
| Back end | FastAPI, SQLite, an event bus streamed to the browser over server-sent events |
| Web | React 19, Vite, TypeScript, zustand, Leaflet night map, `livekit-client` |
| Places | Google Places Text Search and reverse geocoding from the browser's location |

```text
browser ──HTTPS──▶ Caddy ──▶ FastAPI back end ──▶ SQLite, event bus (SSE back to the browser)
   │                              │  place_call / open_room
   └──WebRTC──▶ LiveKit Cloud ◀───┘
                    │ dispatches
                    ▼
             voice worker (LiveKit Agents) ──▶ Sarvam STT/TTS, OpenAI, Synthesia avatar
                    │ Twilio SIP
                    ▼
                 a real phone
```

The worker holds no model of its own: every turn goes through the same `TextConversation` the evals use, so the text evals test exactly what runs on a call.

## Run it locally

Needs Node 20+ and keys for OpenAI, Sarvam, LiveKit Cloud (with a Twilio SIP trunk), Twilio, Google Maps and Synthesia. **One command** installs everything (Python 3.12 included, through uv) and starts the back end, the voice worker and the web app on http://localhost:5173:

```bash
cp .env.example .env    # then fill in the keys
bash scripts/setup.sh
```

The same steps by hand (full details in [AGENTS.md](AGENTS.md)):

1. Copy the environment template and fill in the keys. Keep `TEST_MODE=true`, and set `ALLOWED_NUMBERS` and `DEMO_ROUTE_PHONE` to your own phone.

   ```bash
   cp .env.example .env
   ```

2. Create the Python environment and install the packages.

   ```bash
   uv venv --python 3.12 && uv pip install -r pyproject.toml
   ```

3. Install the web app's packages.

   ```bash
   npm --prefix web install
   ```

4. Start the back end.

   ```bash
   .venv/Scripts/python -m uvicorn backend.main:create_app --factory --port 8000
   ```

5. Start the voice worker.

   ```bash
   .venv/Scripts/python -m voice.worker dev
   ```

6. Start the web app, then open http://localhost:5173.

   ```bash
   npm --prefix web run dev
   ```

On macOS or Linux, use `.venv/bin/python` in place of `.venv/Scripts/python`.

**Tests**, which never touch the network:

```bash
.venv/Scripts/python -m pytest
```

```bash
npm --prefix web test
```

**Evals:** a model plays the tradesperson or the candidate. 12 scenarios cover being available, busy, voicemail, a Hindi reply to a Telugu call, a wrong number, booking, the voice brief, and screening (interested and not interested). Results and transcripts go to `evals/last_run.md`.

```bash
.venv/Scripts/python -m evals.run
```

**Type a conversation** instead of phoning:

```bash
.venv/Scripts/python -m voice.text_mode --language te --calling "<shop name>" --work "..." --area "<colony, locality>"
```

## Deploy (AWS)

[`deploy/`](deploy) sets up one server: a c7i.xlarge (4 vCPU, no GPU) in us-east-1 (the event's AWS account allows only us-east-1 and us-west-2), Ubuntu 24.04, Caddy with an automatic HTTPS certificate on `<ip>.sslip.io`, and systemd services for the back end and the worker. The worker restarts itself if LiveKit drops.

1. Create the server once; this prints its IP.

   ```bash
   bash deploy/provision.sh
   ```

2. Deploy the current `main`. It refuses while a job on the server is mid-call.

   ```bash
   bash deploy/push.sh <server IP>
   ```

The server's worker registers under its own LiveKit agent name (`AGENT_NAME=agenthire-cloud`), so a laptop's worker and the server's never take each other's calls.

## Repository map

| Path | What it is |
|---|---|
| `backend/` | FastAPI app: jobs and their steps (`jobs/`), finders, writers, guardrails, calls, messages |
| `voice/` | The conversation engine (`engine/`, no LiveKit code), the LiveKit worker, text mode, kinds and style files |
| `web/` | The React app: one screen per step in `src/screens/` |
| `evals/` | Scenario runner and scenarios |
| `deploy/` | Server provisioning and deployment |
| `docs/` | [Scope](docs/SCOPE.md), [tech stack](docs/TECH_STACK.md), [HLD](docs/HLD.md), [LLD](docs/LLD.md), and the [build plan with its progress log](docs/BUILD_PLAN.md) |

## What came from earlier work

The builder's earlier project SevaMitra (a voice service agent on the same stack) was the reference. Its approach informed the phone setup (Twilio trunk, LiveKit SIP trunks and dispatch), the worker's structure, turn-taking settings and the browser event-stream client. Copying from one's own earlier work was confirmed as allowed by the organisers. Everything specific to AgentHire was written at the event: the data-driven conversation kinds, both sides' job flows, the grounding checks, the writers, the web app and the evals.

## What's next

- WhatsApp and voice notes as the way in, since most users already live there.
- Memory of providers and preferences ("call the same plumber as last time").
- More sources (JustDial, Urban Company) and, for hiring, job-board applicants with consent, so screening calls reach real candidates.

# AGENTS.md: run AgentHire from this zip

AgentHire is a voice assistant that hires people for you. You say who you need; it finds real people, phones them in their own language, and brings back a shortlist with their own words as proof. Two sides: **Gig worker** (a plumber or electrician at home) and **IT hire** (screening candidates for a role).

**Fastest way to see it working: the live deployment, https://3-213-208-226.sslip.io** (no login). It is in test mode, so every phone call rings the builder's phone, and the builder answers as the provider or the candidate.

The rest of this file is how to run it yourself from this zip. `README.md` explains what it is and how it is built; `docs/SUBMISSION.md` has the evidence of results and what is built, reused and simulated.

## 1. What you need

| Need | Version or note |
|---|---|
| Linux (Ubuntu 24.04 tested) or Windows | macOS should work but is untested |
| Python | 3.12 exactly (`requires-python = ">=3.12,<3.13"`) |
| Node.js | 20 or newer (built with 24) |
| Internet access | speech, models, maps and calls are cloud services |
| A browser with a microphone | Chrome. The voice brief needs the microphone and the start screen asks for location; both need `localhost` or HTTPS |
| Accounts and keys | **In the submission zip, `.env.example` holds working keys for judging**: rename it to `.env` (section 2). In the public GitHub repository the same file is blank. |

## 2. Environment variables (`.env`)

**From the submission zip:** `.env.example` already holds working keys, provided by the builder for judging only. **They will be rotated after the event (22 Nov 2026)**, so they stop working then. Rename it and the app is ready:

```bash
cp .env.example .env
```

- `TEST_MODE=true`: providers are found for real, but **every call and SMS goes to `DEMO_ROUTE_PHONE`, which is set to the builder's phone**. To answer the calls yourself, set `DEMO_ROUTE_PHONE` to your own number with its country code (e.g. `+919000000000`) and add it to `ALLOWED_NUMBERS`. A number not in `ALLOWED_NUMBERS` is never dialled.
- `AGENT_NAME=agenthire-judges`: your voice worker registers under its own name on the shared LiveKit project, so it never takes the builder's or the live server's calls, and they never take yours. Keep it.

**From the public repository:** the file is blank. Copy it to `.env` and fill in your own keys as below.

The app reads `.env` from the repository root (only `backend/settings.py` reads it). Product rules (call length, calling hours, voices, turn-taking) are in `config.yaml` and need no change.

| Variable | What it is | Needed for |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key | everything that talks or writes |
| `LLM_MODEL_FAST` | `gpt-5.4-mini` | small writing tasks |
| `LLM_MODEL_SMART` | `gpt-5.5` | conversations, result writing, scoring, web crawl |
| `SARVAM_API_KEY` | Sarvam AI key (speech to text `saaras:v4`, voices `bulbul`) | voice brief and calls |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | a LiveKit Cloud project | voice brief and calls |
| `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` | a LiveKit outbound SIP trunk (here on a Twilio Elastic SIP trunk) | real phone calls only |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | Twilio account and its phone number | the SMS after a booking; the caller ID |
| `TWILIO_EDGE` | `singapore` | Twilio region |
| `GOOGLE_MAPS_API_KEY` | Google Maps Platform key with **Places API (New)** and **Geocoding API** enabled | finding providers, the start screen's address |
| `AVATAR_PROVIDER`, `AVATAR_API_KEY` | `synthesia` and a Synthesia key | the real-time avatar in the voice brief (optional: without it the brief shows an animated orb) |
| `HINDSIGHT_*` | optional memory service | not needed |
| `TEST_MODE` | keep `true` | every call and SMS goes to `DEMO_ROUTE_PHONE` instead of the real provider |
| `ALLOWED_NUMBERS` | your own phone number(s) with country code, comma-separated, e.g. `+919000000000` | dialling guardrail |
| `DEMO_ROUTE_PHONE` | the phone that rings in test mode (must be in `ALLOWED_NUMBERS`) | calls and SMS |
| `DEMO_ROUTE_EMAIL` | leave empty | not used |
| `INTERNAL_API_TOKEN` | leave empty locally; any random string on a public server | worker-to-back-end events |
| `DATABASE_PATH` | `data/agenthire.db` | SQLite file, created on first start |
| `AGENT_NAME` | `agenthire-judges` in the zip; with your own LiveKit project it can stay empty (the worker then registers as `agenthire`). Each machine sharing one LiveKit project needs its own name | which worker takes which jobs |
| `BACKEND_URL` | `http://127.0.0.1:8000` | where the worker reaches the back end |

Check the keys (prints only whether each is set and reachable, never the values):

```bash
.venv/bin/python scripts/check_keys.py
```

**What works with which keys:** with only `OPENAI_API_KEY` you can run the tests, the evals and text mode (section 5). Add Google Maps for providers and addresses, LiveKit and Sarvam for the voice brief in the browser, and the SIP trunk and Twilio for real phone calls.

## 3. Install

From the repository root. On Windows use `.venv\Scripts\python` wherever this says `.venv/bin/python`.

With [uv](https://docs.astral.sh/uv/), which fetches Python 3.12 itself if the machine lacks it (install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh`, or `pip install uv`):

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r pyproject.toml
.venv/bin/python -m voice.worker download-files
npm --prefix web ci
```

The third command fetches the voice activity and turn-detection models once. Without `uv`, with Python 3.12 installed, install the pinned list from `pyproject.toml` with pip:

```bash
python3.12 -m venv .venv
.venv/bin/python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/agenthire-requirements.txt
.venv/bin/pip install -r /tmp/agenthire-requirements.txt
```

## 4. Start everything (three processes)

Run each in its own terminal, from the repository root, in this order.

```bash
.venv/bin/python -m uvicorn backend.main:create_app --factory --port 8000
```

```bash
.venv/bin/python -m voice.worker dev
```

```bash
npm --prefix web run dev
```

Then open **http://localhost:5173**. The web app proxies the API to the back end on port 8000. Check the back end with `curl http://127.0.0.1:8000/health` (returns `{"status":"ok"}`).

- The worker registers with LiveKit (`registered worker` in its output). If LiveKit is unreachable for about 2 minutes it exits; restart it, or run it in a loop: `while true; do .venv/bin/python -m voice.worker dev; sleep 5; done`.
- Never restart the back end or worker while a call is in progress: it cuts the call.

**On a fresh Ubuntu server with HTTPS** (needed when the browser is on another machine, for the microphone and location): `deploy/setup.sh` installs Python 3.12, Caddy (automatic HTTPS on `<ip-with-dashes>.sslip.io`) and two systemd services. It clones the public repository `https://github.com/sanithvarma0/agenthire`. Open ports 80 and 443, then:

```bash
npm --prefix web ci && npm --prefix web run build
mkdir -p /tmp/agenthire-upload && cp -r web/dist .env deploy/setup.sh /tmp/agenthire-upload/
sudo bash /tmp/agenthire-upload/setup.sh <ip-with-dashes>.sslip.io
```

On a server, set `AGENT_NAME` and `INTERNAL_API_TOKEN` in `.env` first. `deploy/provision.sh` and `deploy/push.sh` do all of this from a laptop with the AWS command line.

## 5. Check it without a phone or a browser

```bash
.venv/bin/python -m pytest
```

224 tests; none touch the network or need keys. Web tests and type check:

```bash
npm --prefix web test
```

```bash
npx --prefix web tsc --noEmit -p web
```

**Evals** (needs `OPENAI_API_KEY`; about 10 minutes): 12 scenarios, 3 runs each, a model playing the provider or candidate. Results and every transcript go to `evals/last_run.md` (the committed copy: 36 of 36 pass).

```bash
.venv/bin/python -m evals.run
```

**Text mode** (needs `OPENAI_API_KEY`): talk to the calling agent by typing; you play the provider. An empty line ends it and prints the written result.

```bash
.venv/bin/python -m voice.text_mode --language te --calling "Sri Sai Electricals" --work "a ceiling fan is not working" --area "Madhapur, Hyderabad" --when "tomorrow"
```

## 6. Logins and seed data

None. There are no accounts or logins: open the site and start. No seed data is needed either: the SQLite database is created empty on the first start, and every journey begins from fresh input.

## 6a. For automated reviewers (an AI agent driving a browser)

- **Location:** the Gig worker start screen needs the browser's location and waits for it; a headless browser blocks it by default. Grant the `geolocation` permission and set a position, for example latitude `17.4435`, longitude `78.3772` (HITEC City, Hyderabad). In Playwright: `browser.new_context(permissions=["geolocation"], geolocation={"latitude": 17.4435, "longitude": 78.3772})`. IT hire needs no location.
- **No microphone:** on both start screens tap **"or type it instead"** and type the request; everything after it is the same. The voice brief itself needs a real microphone.
- **Phone calls ring a person.** In test mode every call rings `DEMO_ROUTE_PHONE` (the builder's phone in the zip's `.env.example`). An agent cannot answer it: an unanswered call ends as "no answer" after about a minute, and the journey carries on to the comparison or the shortlist with that outcome. To see a whole call, either put a phone you can answer in `DEMO_ROUTE_PHONE` and `ALLOWED_NUMBERS`, or run the same conversation engine in **text mode** or the **evals** (section 5), where you or a model play the provider or the candidate. The demo video shows real calls being answered.
- **Ports:** web app http://localhost:5173, back end http://127.0.0.1:8000 (`/health`). The live deployment is https://3-213-208-226.sslip.io.

## 6b. What is simulated, mocked or not finished

- **Test mode (on):** providers are real businesses from Google Maps, but every call and SMS goes to `DEMO_ROUTE_PHONE` instead of them, and whoever answers plays the provider. Results are labelled "answered by you" and never stored as the provider's own words.
- **Candidates:** real public profiles found by the web crawl, never contacted; no phone number or email is taken, so every screening call rings `DEMO_ROUTE_PHONE`.
- **Evals:** a model plays the provider or the candidate.
- **Not mocked:** the voice brief, speech to text and voices, the models, the real phone calls (Twilio through LiveKit), the writing, the grounding checks and the shortlist.
- **Not finished:** no WhatsApp (SMS only); no memory of past providers; speech-to-text keeps the call's starting language, so a call that switches between Telugu and Hindi is understood in the first one. Full notes, with evidence of results: `docs/SUBMISSION.md`.

## 7. Journeys to try end to end

Test mode is on, so **every call rings `DEMO_ROUTE_PHONE`**: answer it and play the provider or the candidate. Calls are placed only after you tap to approve them.

**A. Gig worker (home repair)**
1. Open the site, choose **Gig worker**.
2. Pick a language (Telugu, Hindi or English) and allow location (it fills the area; add a house number).
3. Tap **Talk to your assistant**, then the orb. Wait for the greeting to finish, then describe a problem, for example "my kitchen tap is leaking". Confirm its one-line summary. (Or tap "type it instead" and type the problem.)
4. It searches Google Maps for real providers nearby and shows them on a map. Keep the two it picked or swap them, then tap **Call these 2**.
5. Your phone rings twice, one call after the other. Answer as the provider, in Telugu, Hindi or English: whether you can come, when, and the visiting charge. Watch the live transcript.
6. The comparison shows each provider's answers with their own words, and a recommendation. Pick one.
7. Your phone rings once more to confirm the time, then an SMS with the address arrives. The job ends on **Scheduled**.

**B. IT hire (screening)**
1. Choose **IT hire**, enter a company name.
2. Describe the role by voice, or tap "type it instead": for example "We need a backend engineer in Hyderabad, 3+ years of Python and APIs, hybrid".
3. Review the job description, the five screening questions and the scoring guide; edit if you like, then **Approve**.
4. About 20 seconds of web crawling lists public profiles that fit (no contact details are taken).
5. Tick 1 to 3 candidates and tap **Screen**. Your phone rings for each; answer as the candidate (English, with Hindi or Telugu mixed in is fine). The call asks the approved questions, then salary and notice period; up to 5 minutes.
6. The **Shortlist** ranks them: each answer scored 1 to 5 with the quote it rests on. A score is shown only if that quote is in the transcript.

**C. History.** **History** in the top bar lists every request with how it ended. Each job's address (`#/job/<id>`) reopens it at its current step after a reload: everything is stored in SQLite.

## 8. Where things are

| Path | What it is |
|---|---|
| `backend/` | FastAPI app: jobs and their steps (`jobs/`), finders, writers, guardrails, calls (`calls.py`, the only place that dials), messages (`messages.py`, the only place that sends) |
| `voice/` | The conversation engine (`engine/`, no LiveKit code), the LiveKit worker (`worker.py`), text mode, conversation kinds (`kinds.yaml`) and language style files (`style/`) |
| `web/` | The React app; one screen per step in `src/screens/` |
| `evals/` | Scenarios and the runner |
| `deploy/` | Server provisioning and deployment (AWS, Caddy, systemd) |
| `config.yaml` | Product rules: call length, calling hours, voices, turn-taking |
| `CLAUDE.md` | The builder's working notes for coding agents (more commands and conventions) |
| `docs/` | Scope, designs, build log, submission notes |

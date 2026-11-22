# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

There is no code here yet. The repository is for **Builders 2026 (OpenAI x Equal AI)**, a solo in-person hackathon at Equal AI HQ, Hyderabad, on 21–22 Nov 2026.

The project is **AgentHire**, submitted under Track 1 (Build Creative): the user says by voice who they need, and the agent finds people, phones them in their language, and returns a shortlist. **`docs/SCOPE.md` is the agreed scope** and the source of truth for what is in, what is out, the build order, the cut lines and the rules the calling agent must follow. Read it before building anything.

**`docs/BUILD_PLAN.md` is the working document.** It lists the phases, the tasks in order, the test results and a progress log. Work one task at a time in that order. After every task: tick it, add a line to the progress log, and correct any other document the task proved wrong. A phase is not done until its check has been run.

## Commands

Run everything through the project environment (Python 3.12 in `.venv`), from the repository root.

- **Tests:** `.venv\Scripts\python -m pytest` (one file: add its path; one test: add `-k name`).
- **Talk to the agent by typing** (no phone): `.venv\Scripts\python -m voice.text_mode --language te --calling "<shop name>" --work "..." --area "<colony, locality>" --when "..."`. Type the provider's lines; an empty line ends it and prints the result. Lines can also be piped in, one per line.
- **Evals:** `.venv\Scripts\python -m evals.run` (all scenarios, 3 runs each, about a minute; `--only <id> --runs 1` for one). A model plays the provider; results and transcripts go to `evals/last_run.md`. They call real models, so results vary: rerun before concluding a change broke something, and read the transcript of any failure. The larger model plays the provider; check whether a failure is the agent, the simulated provider or the scenario's expectation before changing the agent.
- **Back end:** `.venv\Scripts\python -m uvicorn backend.main:create_app --factory --port 8000`.
- **Web app:** `npm --prefix web run dev` (http://localhost:5173; it proxies the API paths to the back end on port 8000, so start the back end first). Type check: `npx --prefix web tsc --noEmit -p web`. Tests: `npm --prefix web test`. In Claude's browser pane, start it with the `web` entry in `.claude/launch.json`; the pane blocks location, so stand one in from the page for checks.
- **Voice worker:** `.venv\Scripts\python -m voice.worker dev` (registers as `agenthire` with LiveKit Cloud; needs the back end running). It exits for good if LiveKit is unreachable for about 2 minutes (16 retries; seen on the venue Wi-Fi), so run it in a loop that restarts it on exit, appending to `data/worker.log`.
- **Voice brief:** open http://localhost:5173 in a real browser (the Claude pane blocks the microphone), choose a language, confirm the address, tap "Talk to AgentHire", then tap the orb. Needs the back end and worker running.
- **Never restart the worker or back end while a job may be calling** (check the job's step first, or ask the builder): a restart mid-call once left the builder on a silent line. The dialler now rings only after the agent joins, but a restart still cuts a live call.
- **Whole flow from the web app** (test mode): start a job in the browser, approve, and the calls ring the builder's phone one after another. Tell the builder before tapping "Call these 2".
- **Test call to the builder's phone** (development only, numbers in `ALLOWED_NUMBERS`): `.venv\Scripts\python scripts\call_me.py --language te --calling "<shop name>" --work "..." --area "<colony, locality>"`. It goes through the back end's `POST /dev/test-call` (test mode only), so the real guardrails apply. Needs the back end and worker running; prints the transcript and the written result after the call. Tell the builder before dialling: they answer and play the provider. Restart the back end or worker after changing their code.
- Logs from background runs go to `data/backend.log` and `data/worker.log` (git-ignored). Set `DATABASE_PATH` to a scratch file for throwaway checks so `data/agenthire.db` stays clean.
- **Indian-script input in manual checks:** send it from Python, not curl. Git Bash passes curl arguments through the Windows code page and Telugu arrives as question marks.
- **Check the keys in `.env`:** `.venv\Scripts\python scripts\check_keys.py`. It prints status only and uses only the standard library.
- **Deploy:** `bash deploy/provision.sh` once (AWS, ap-south-1, c7i.xlarge, Elastic IP), then `bash deploy/push.sh <ip>` for each release (deploys GitHub's `main`; refuses while a job on the server is calling). The server's worker uses `AGENT_NAME=agenthire-cloud`. As of Sun 22 Nov, 5 AM the AWS account is not yet activated for any service, so nothing is deployed.
- **Install libraries:** `uv pip install <package>` with the environment active. On the venue Wi-Fi the package index drops in and out, so a failed install is usually worth one retry. Add anything installed to `pyproject.toml` with its version.

More commands are added here as they come to exist.

## Code layout so far

- `backend/settings.py`: the only place that reads `config.yaml` (product rules) and `.env` (secrets). Test mode is on unless switched off.
- `backend/models.py`: the typed objects passed between components. Add a field here before passing new data around.
- `backend/db.py`: SQLite storage, six tables, JSON stored as text.
- `backend/events.py`: the event bus and the two event endpoints. Publish every event through `EventBus.publish`, never `db.add_event` directly, or live watchers are not woken.
- `backend/main.py`: the FastAPI app factory. Shared objects live on `app.state` (`settings`, `db`, `bus`).
- `backend/jobs/api.py`: the job endpoints the web app uses (`POST /jobs`, `GET /jobs` (with `limit`, and each job's outcome for History), `GET /jobs/{id}`, `POST /jobs/{id}/approve`). `backend/jobs/steps.py`: the steps that run after a response (`find`: brief writer, then Places, then people saved best first); a step that cannot go on calls `fail` with a reason the screen shows. Tests put a fake model on `app.state.openai` and a fake Google on `app.state.http`; never let a test reach the network. `backend/writers/brief.py` turns a request into service words and work. `backend/jobs/calling.py` runs the calls after approval (one at a time, results written and grounded in the back end, Skip and Stop through `CallControl`); tests fake the line and the worker with a dialler that publishes the worker's events. `backend/jobs/reporting.py` and `backend/writers/comparison.py` recommend one provider after the calls; numbers in the reason are checked against the facts. `backend/jobs/briefing.py` runs the voice brief (a browser room through `Dialler.open_room` and `browser_token`; the worker joins it like a phone call). `backend/jobs/confirming.py` makes the confirmation call and sends the address SMS through `backend/messages.py`, the only place that sends messages, always after `can_message`. Tests must set `app.state.sms` to a fake: an unset sender is the real Twilio. `GET /location` (in `backend/providers.py`) gives the Start screen the area and a street address.
- **Company side** (LLD section 17): `backend/jobs/roles.py` (`POST /roles`, posting edit and approve; everything else reuses the job endpoints), `backend/writers/posting.py`, `steps.write_role`; sourcing is `steps.source` with `backend/writers/sourcing.py` (Responses API with the web search tool; candidates saved with `source = web`, display only; `POST /jobs/{id}/approve` refuses them); `screens/Candidates.tsx`; the `role_brief` kind runs on the same brief machinery (`briefing.py` picks the kind by the job's side). Web: `screens/Hire.tsx` (`#/hire`) and `screens/Posting.tsx`; `roleOf(job)` reads a company job's brief.
- **Scratch checks in the browser:** run a back end with `DATABASE_PATH=data/scratch-check.db` on port 8001 and start `web-scratch` from `.claude/launch.json` (port 5174, proxied to 8001), so live checks never touch `data/agenthire.db`.
- `web/`: the React app. `src/api.ts` holds the types and calls, `src/store.ts` the job and its live event stream, `src/theme.css` the night theme (the design tokens and every class; reuse them rather than adding inline styles), `src/screens/` one file per screen, `src/components/Frame.tsx` the top bar, step rail, job summary and the two-column `JobLayout` every job screen uses (stage left, rail right, one column below 920px), `src/components/NightMap.tsx` the map (Leaflet, Esri dark gray tiles; no key). The address bar holds where you are: the bare address is the choice page (`screens/Choose.tsx`, gig worker or IT hire), then `#/gig`, `#/hire`, `#/history` or `#/job/<id>`. `components/Scenes.tsx` holds the drawn widgets on the start screens; prefer a picture to a paragraph there.
- `voice/kinds.yaml`: the conversation kinds, written as requirements for the model. Add a kind here, not in code. `home_call` opens in two steps: greet and check the shop's name (`calling`), then, once confirmed, colony and locality, the problem and the ask (`second_turn_requirements`).
- `voice/style/<language>.yaml`: how to talk in each language (rules plus formal-to-natural examples), added to the instructions. Change the register here, not in the engine.
- `voice/engine/`: the conversation engine, with no LiveKit code. `kinds.py` loads kinds and builds a record for one conversation; `prompt.py` builds the instructions and the per-turn status note. `voice/tests/test_prompt.py` has a test that fails if the engine or kinds file names a trade or place or contains scripted Hindi or Telugu; keep it passing.
- `voice/engine/state.py` and `voice/engine/tools.py`: the live state of a conversation and the four tools. Rules that matter (a fact must quote the person's own words, a do-not-call ends the call, no ending without an outcome) are enforced here in code, not only in the prompt. A runner must call `state.person_said(text)` per transcript and `state.after_agent_reply()` per spoken reply.
- `backend/writers/call_result.py` and `backend/guardrails.py`: after a call, the larger model writes the result from the whole transcript and `ground_call_result` checks every fact against the line it cites. The user sees this result, not the one recorded live, because the writer sees the whole call (it fixed an "available = yes" the live agent took from a greeting). `backend/text_match.py` is the shared word matcher.
- `backend/finders/places.py` and `backend/providers.py`: real providers near the user's browser location (`POST /providers/search`), via Google reverse geocoding and Places Text Search with the user's own service words. Radius, ranking weights and the number shown are in `config.yaml`.
- `backend/calls.py` and `backend/guardrails.py`: the only way to dial is `place_call`, which runs `can_dial` first (approval, calling hours except the builder's own numbers, do-not-call, 3 calls per job). Never dial from anywhere else.
- **`TEST_MODE` is the demo toggle.** On: providers are found for real but every call rings `DEMO_ROUTE_PHONE` (the builder plays the provider). Off: real providers are called. Keep it on unless the builder says otherwise. A rerouted call has `routed_to` set; never show its result as the provider's own, never save memory from it against the provider, and route messages the same way. `backend/dev.py` holds test-mode-only endpoints.
- `voice/worker.py`: the LiveKit worker. It waits a limited time for the other side (`JOIN_TIMEOUT_SECONDS`) and always reports the conversation ended; `EventSink` delivers every event in order, including the last one before closing. Its session has no model on purpose: every turn goes through `TextConversation`, so text-mode evals test exactly what runs on calls. Do not hand turns to LiveKit's own model and tools; that made the agent speak twice after a tool call. The worker never dials; it only joins rooms the back end dispatches it to.
- **Models:** conversations run on `LLM_MODEL_SMART` through the Responses API, streamed (`TextConversation._complete`; reasoning effort in `config.yaml`, `voice.reasoning_effort`). There is no in-call fact check: the model decides with the whole conversation, and the result after the call is written and grounded from the transcript. Prefer prompt and kind requirements over new code rules; add a code rule only when the model keeps failing and the builder agrees.
- `voice/engine/speech_text.py`: `clean_for_speech` removes characters no voice in the app can say; `normalise_transcript` turns Kannada script (Sarvam's misdetection of colloquial Telugu) into Telugu; `drop_repeated_question` stops the agent ending two turns with the same question; `strip_leaked_tool_text` removes tool-call JSON a model wrote into its reply, so it is never spoken; `keep_final_draft` keeps only the rewrite when a reply holds a draft and then a rewrite. `voice/engine/opening_check.py` checks the opening before it is spoken and regenerates it once if it fails. When a prompt rule does not hold up in the evals, enforce the behaviour in code like these. Outcome meanings live once in `backend/models.py` (`OUTCOME_MEANINGS`), shared by the tools and the writer.
- **Engine source stays plain ASCII.** Write Indian-script ranges as code points (`chr(0x0C00)`), never as literal characters, or the no-hardcoding test fails.
- **Take times from the clock** (`date`) before writing them into the progress log; do not estimate.
- `config.yaml` also holds the speech settings. Voices are listed in `voice.voices` with their Sarvam model and gender, and `voice.language_voice` picks one per language (Telugu: `kavitha_te_conversation`, the builder's choice; Hindi: `shubh`; English: `roopa_en_conversational`, female to match the avatar). A voice's gender must be right: the agent uses it for gendered word forms. Change the Telugu voice there, not in code.

## This is not SevaMitra

`C:\Users\WTSL_HYD\Downloads\CLAUDE.md` describes SevaMitra, a Paytm hackathon project. Claude Code loads it here only because it sits in an ancestor directory. It is a different project: its rules (mock Paytm APIs, Sarvam STT/TTS, tool contracts, demo scenarios, repo layout) do not apply to work in this repository.

## Rules of the event (confirmed in the kickoff deck)

- **Code reuse from the builder's earlier projects is allowed.** The deck says code is written at the event (open-source libraries and the builder's own tools and coding agents are fine). The builder asked the organisers on Sat 21 Nov and was told that copying from their own earlier work is acceptable. `../sevamitra-main` uses nearly the same stack and is the main reference. `../WelHire` is a product built for the builder's employer, so check with the builder before copying code from it, as opposed to reading it for approach.
- **Solo only.** No teams and no outside help.
- **Code freeze is Sun 22 Nov, 2:00 PM IST.** No late entries. Judging runs 2:00–5:30 PM and the finale is at 6:00 PM.
- **Provided:** OpenAI API credits and an AWS account for hosting. Default to OpenAI models and AWS unless there is a reason not to.

## The three tracks (pick one)

| Track | Brief | Must show | What stands out |
|---|---|---|---|
| **Build Creative** | Personal context into everyday AI products. Find a real user and an unmet need. Idea prompts: camera, Drive, SMS, mail, anything personal. | A working journey from raw input to a useful outcome | An original idea, backed by a working product |
| **Build Challenging** | Voice AI for India; invent in the harness around the model. Idea prompts: smart dictation, semantic VAD, full-duplex model, Indian names and entities. | The same recordings on a base model and on your system | A measurable improvement on a frustration everyone knows |
| **Build Ambitious** | A SaaS product in a day. Name a reference product (Mixpanel, Datadog, Canva, Lovable, any SaaS), innovate on it, ship it with AI. | The chosen product working end to end; completeness is the core of it | Speed and engineering depth |

## Submission and judging

- **Submit three things:** the code repository, a working demo (deployed link or recording), and 4–5 slides covering the problem, what was built, how it works and what is next.
- **60 builders → 10 shortlisted → 3 winners.** The Equal AI team shortlists from the code, demo and slides alone, so the repository and README are read by engineers and the product must make sense without a presenter. The jury picks winners after live demos.
- **Judges score three things:** a working end-to-end product demo, how AI-native it is, and presentation and craft.
- **Jury:** the OpenAI India developer relations lead and Equal AI's leaders. The chief guests are former heads of MeitY and the IndiaAI Mission.

## What Equal AI is building (context for choosing an idea)

- **Roadmap:** personal AI calls today (answers calls, speaks for the user, leaves a summary and actions), personal AI messaging next ("AI-powered WhatsApp", voice notes turned into actions), then personal AI experts built into messaging (doctor, credit advisor, travel agent and about 25 other agents).
- **Core loop:** personal context reveals intent, intent becomes actions on the user's behalf, and every fulfilment returns as deeper context.
- More background is in `docs/equal-ai-research.md`.

## Working constraints

- **Working end to end beats feature-complete.** One person has 28 hours, so scope a minimum version first. The plan in `docs/builders-event-context.md` is: end-to-end flow deployed by midnight Saturday, polish on Sunday morning, no big changes after 1:00 PM Sunday.
- Keep the code readable and the README current as the project grows, because the shortlist is decided partly on the code.

## Docs

- `docs/BUILD_PLAN.md`: phases, ordered tasks, test results and the progress log.
- `docs/SCOPE.md`: the agreed AgentHire scope.
- `docs/TECH_STACK.md`: what it is built with, the six tests that decide open choices, and the `.env` variable names.
- `docs/HLD.md`: components, how a conversation works, memory types, structured data, tools, guardrails and evals.
- `docs/LLD.md`: folder layout, tables, typed objects, job steps, endpoints, voice worker, guardrail checks and evals for the home side. Its first section, "No hardcoding", is a rule for all code: no fixed sentences, word lists or built-in categories.
- `docs/Tracks.txt`: the track announcement, rules and submission list as posted.
- `docs/Builders-Kickoff-2026-11-21.pdf`: the kickoff deck. It is 28 MB and image-only, so the Read tool cannot open it; the sections above summarise all 16 slides.
- `docs/builders-event-context.md`: pre-event notes and the hour-by-hour build plan. Its "open questions" are now answered above.
- `docs/equal-ai-research.md`: Equal AI's product, history and funding.

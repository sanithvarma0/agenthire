# AgentHire — Tech Stack

Agreed on Sat 21 Nov 2026, about 3:10 PM IST. Read `SCOPE.md` first; this document says what AgentHire is built with and why.

## 1. Summary

| Layer | Choice | Status |
|---|---|---|
| Voice framework | LiveKit Agents (Python), one worker for browser, phone and avatar | Decided |
| Phone line | Twilio SIP trunk into LiveKit | Decided |
| Speech-to-text and text-to-speech | Sarvam, for every call | Decided and confirmed by test 3 on 21 Nov |
| Model in calls | A small, fast OpenAI model with reasoning off | Decided; exact model name confirmed at setup |
| Model for writing and scoring | A larger OpenAI model | Decided; exact model name confirmed at setup |
| Avatar | A hosted provider with a LiveKit plugin | Provider decided by test |
| Avatar backup | None | The self-hosted option needed a GPU, and the organisers ruled GPUs out |
| Home-side sources | Google Places, then JustDial, then Urban Company | Places decided; the other two are added one at a time for comparison |
| Company-side sourcing | Web search for public LinkedIn profiles (OpenAI Responses with the web search tool); no browser agent | Decided Sun 22 Nov, 3:40 AM; display only |
| Resume reading | PDF text extraction, then an OpenAI structured call | Decided |
| Back end | FastAPI, SQLite, server-sent events to the browser | Decided |
| Front end | React, Vite, TypeScript, Tailwind | Decided |
| Email | AWS SES | Decided; see section 4 |
| Hosting | One AWS server | Decided; done at the end |
| Python | 3.12, pinned with `uv` | Decided |
| Node | Version 24 with `pnpm` (already installed) | Decided |

## 2. Voice

### Framework

LiveKit Agents in Python. One worker process handles all four kinds of conversation:

| Conversation | Who is on the other end | Channel |
|---|---|---|
| Voice brief | The user | Browser |
| Home-side call | A tradesperson | Phone |
| Screening call | A job applicant | Phone |
| Avatar interview | A shortlisted candidate | Browser, with avatar video |

Each conversation is started with a job description passed as data: the language, the goal, the questions to ask, and what the agent may share. The worker has no electrician-specific or recruiter-specific code.

### Phone

- Twilio Elastic SIP trunk connected to LiveKit's SIP service. Outbound calls are placed by asking LiveKit to dial a number into a room. The trunk, its LiveKit outbound and inbound trunks and a dispatch rule already exist from SevaMitra (verified through both APIs on 21 Nov), so no phone setup is needed.
- Twilio's Singapore edge, so audio does not travel through the United States.
- **Caller ID is international.** Twilio requires calls into India to come from a non-Indian number, so tradespeople will see a foreign number. Expect lower pickup rates and plan to dial more than three people to reach three.
- SMS for the booking confirmation and close-out messages goes through Twilio. Delivery to Indian numbers is checked in the first tests.

### Speech

- **Sarvam for every call.** Speech-to-text runs in code-mix mode, which keeps English words in Latin script and Indian-language words in their own script. That also covers the screening call, where the agent speaks English and the applicant may mix in Hindi or Telugu.
- Settings: speech-to-text model `saaras:v4` in `codemix` mode. Text-to-speech uses one voice per language, set in `config.yaml` (`voice.language_voice`), each with its model and gender (`voice.voices`):
  - **Telugu:** `kavitha_te_conversation` (female, `bulbul:v4-flash`) is the default, chosen by the builder on 21 Nov after hearing 32 samples and comparing it with `pooja_te_conversation` on live calls. `config.yaml` (`voice.language_voice.te`) holds the choice. Alternatives already listed: `kavitha_te_conversation` (female) and `tarun_te_narration` (male), both `bulbul:v4-flash`.
  - **Hindi and English:** `shubh` (male, `bulbul:v3`).
  - When a call switches language, the voice switches to that language's voice, and the agent's gendered word forms follow it. Streaming was tested for both: first audio in 0.45 s (Telugu) and 0.35 s (Hindi).
  - Sarvam lists more male voices for `bulbul:v3` (such as `tarun`, `gokul`, `vijay`), but the installed LiveKit plugin (1.8.11) refuses them.
- **Test 3 result (21 Nov):** on real Telugu phone calls, the Sarvam pipeline transcribed every answer correctly and replied in about 1.8 seconds. OpenAI's `gpt-realtime-2.1` replied faster (about 0.6 seconds) and understood the answers, but its transcript of the caller was unreliable, including wrong-language output. Reports and the grounding check depend on the transcript, so Sarvam is used for calls. Details are in `BUILD_PLAN.md`, section 4.

### Turn-taking: starting values

These are the settings that worked on phone calls in SevaMitra. They are starting points to tune, not final values.

| Setting | Starting value |
|---|---|
| End-of-turn wait on phone calls | 0.8 s minimum, 3.5 s maximum |
| Speech needed to interrupt the agent | 0.8 s and at least 2 words |
| Interruption detection | Local voice detection, not the cloud model (which hit rate limits) |
| Delay before the greeting after pickup | 1.0 s |
| Greeting and AI disclosure | Cannot be interrupted |
| Acknowledgement words ("haan", "ఆ", "ok", "ji") | Never treated as an interruption |
| Noise cancellation | Telephony mode on phone calls |

### Design choices

- **No LangGraph.** LiveKit's own tool calling is enough. There is no money movement to guard, so the extra layer is not needed.
- **Replies are not streamed** (changed on 21 Nov, task 2.1). Each turn runs through the same conversation engine the evals test, and the reply is spoken once its one or two sentences are complete. Streaming through LiveKit's own model handling made the agent speak twice after a tool call.
- **Speech-to-text runs in auto-detect mode** (`stt_language: unknown`). Fixed to Telugu it wrote Hindi speech in English letters; fixed to Hindi it translated Telugu into Hindi. Only the speaking voice switches language.
- **Text mode from the first day.** The same conversation logic runs as typed text with no audio, so behaviour can be tested without phoning anyone.
- **Structured results come from two places:** a tool the agent calls at the end of the conversation, and a separate pass over the full transcript afterwards. The transcript pass is the one reports are built from.

## 3. Models

- **In calls:** a small, fast OpenAI model with reasoning switched off. SevaMitra's comparison found that this gave reliable tool calls in Hindi and Telugu at about one second per reply, and that two older small models skipped tool calls for Indian-language input.
- **For writing and scoring:** a larger OpenAI model, used for the job description, screening questions, resume reading, shortlist scoring and final reports. These are not time-critical.
- **Model names live in `.env`.** Confirmed on 21 Nov against the models the event key can use: `gpt-5.4-mini` for calls and `gpt-5.5` for writing and scoring. Changed Sun 22 Nov at the builder's request (accuracy first, credits are plentiful): conversations also run on `gpt-5.5`, reasoning `low`, through the Responses API and streamed (see `LLD.md`, "Models and streaming"). The key also lists `gpt-5.6-luna`, `gpt-5.6-sol` and `gpt-5.6-terra`, which have not been looked up, and `gpt-realtime-2.1`, which is the model to use in the speech test.
- OpenAI credits are provided by the event, so cost is not a constraint.

## 4. Finding people

### Home side

| Order | Source | How | Notes |
|---|---|---|---|
| 1 | Google Places (New), Text Search | Official API | Returns name, rating, review count, location and phone number. Needs a Google Cloud project with billing. Free allowance is 1,000 requests a month, or 7,000 on India billing |
| 2 | JustDial | Playwright script | Protected by bot detection that blocks server addresses quickly. Run from the laptop in small numbers, and cache results |
| 3 | Urban Company | Playwright script | Expected to return no phone numbers, because bookings go through its app. Included to show the comparison |

Google Maps is not scraped separately, because Places returns the same data.

Results from each source are shown side by side so the comparison is visible. Only numbers the user approves are dialled.

### Company side

Two steps:

1. **Search.** An OpenAI model with web search finds public LinkedIn profiles matching the role and city. This usually returns the name, headline and profile link.
2. **Read.** A browser-use agent opens each profile to read the current role and experience. Signed out by default. A new LinkedIn account created for this may be used signed in; new accounts tend to be restricted quickly, so the signed-out search remains the base.

Rules for sourced candidates:

- They are displayed only: name, current role, experience and profile link.
- They are never called or emailed. In the demo, an invite for a sourced candidate goes to the builder's own phone and email, with a visible "demo routing" label.
- Screening and interview results are recorded under whoever actually applied and answered, never under a sourced profile.

Indeed is not used: it lists jobs, and candidate resumes need a paid employer account. Naukri and other job-board connectors are future work for the slides.

### Tools considered

| Tool | Decision |
|---|---|
| browser-use | Used for the LinkedIn read step. Slow and costs tokens on every step, which is acceptable here |
| Playwright (library) | Used for the JustDial and Urban Company scripts |
| playwright-mcp | Not used in the product. It connects a coding assistant to a browser; plain Playwright is faster and repeatable inside an app |
| agent-reach | Not used. It is a command-line tool for coding assistants, not a library to build on |

### Email

AWS SES, in its default sandbox mode, which only sends to verified addresses. That matches the demo rule that invites go only to the builder's own email.

## 5. Avatar

- **First choice: a hosted provider with a LiveKit plugin.** LiveKit lists 17 avatar providers. The agent's audio is sent to the avatar service, which publishes synchronised audio and video into the room.
- **Order to try:** Synthesia (advertises 500 free minutes), then others with a free tier. Anam's free tier caps sessions at 3 minutes, which is too short for a five-question interview.
- **No self-hosted backup.** LiveTalking with Wav2Lip was the planned backup, but it needs a GPU server and the organisers told the builder not to use GPUs. If the hosted avatar fails, the fallback is a voice interview with a still image, which falls short of the submitted text.
- **Synthesia specifics:** the plugin is `livekit-plugins-synthesia==1.8.11` (newer versions need a newer LiveKit). It needs one to five avatar IDs from the workspace's gallery, each starting with `av_`; the API key cannot list them, so they are copied from the Synthesia dashboard.
- **Ruled out for a live interview:** SadTalker (produces video files, not live video) and LivePortrait (animates from motion, not audio). No speed data was found for Duix-Avatar.

## 6. Decided by test

These run once the accounts and keys are set up, before feature work.

| # | Test | Decides |
|---|---|---|
| 1 | Search Places for electricians near the venue | Whether listings come back with phone numbers |
| 2 | Call an Indian mobile from the Twilio number, and send it an SMS | What the caller ID looks like and whether SMS arrives |
| 3 | Hold a short Telugu phone conversation on Sarvam, then on GPT-Realtime-2 | Which speech option is used |
| 4 | Get a talking avatar in the browser, driven by our own voice agent, within 30 minutes | Which avatar provider is used |
| 5 | Search signed out for "AI engineer Hyderabad" profiles | Whether the search step returns ten real profiles |
| 6 | Check the AWS account's GPU limit | Whether the avatar backup exists at all |

## 7. App

- **Back end:** FastAPI on Python 3.12, with SQLite as the only database. Every event in a conversation (speech, tool call, result) is stored and pushed to the browser over server-sent events, which is how the live transcript works.
- **Front end:** React with Vite, TypeScript and Tailwind. The LiveKit browser library handles the microphone for the voice brief and the avatar interview.
- **Resume reading:** extract the text from the PDF, then one OpenAI call that returns structured fields.
- **Hosting:** one AWS server running the back end, the voice worker and the built site, behind HTTPS. The browser microphone does not work without HTTPS. Set up at the end.

## 8. Reference code

Reusing code from the builder's earlier projects is allowed; the builder confirmed this with the organisers on 21 Nov.

| Project | Use |
|---|---|
| `../sevamitra-main` | Main source for reuse. Same stack. Most useful: the phone setup script (Twilio trunk, LiveKit trunks, dispatch rule), the worker structure, the turn-taking and backchannel handling, the event stream and its browser client |
| `../WelHire` | Reference for approach: interview flow, question handling, scoring rubric and report shape. It was built for the builder's employer, so check with the builder before copying code from it |

The README states which parts were adapted from SevaMitra.

## 9. Accounts and keys

All keys go in `.env`, which is never committed. Names only:

| Service | Variables |
|---|---|
| OpenAI | `OPENAI_API_KEY`, `LLM_MODEL_FAST`, `LLM_MODEL_SMART` |
| Sarvam | `SARVAM_API_KEY` |
| LiveKit | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` |
| Twilio | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `TWILIO_EDGE` |
| Google | `GOOGLE_MAPS_API_KEY` |
| Avatar | `AVATAR_PROVIDER`, `AVATAR_API_KEY` |
| AWS | Set through the AWS command-line tool, not `.env` |
| Safety switches | `TEST_MODE`, `ALLOWED_NUMBERS`, `DEMO_ROUTE_PHONE`, `DEMO_ROUTE_EMAIL` |

Accounts to set up after the design documents are done: LiveKit Cloud, Google Cloud with billing, the event's AWS account, and an avatar provider.

## 10. Sources checked on 21 Nov

- [LiveKit virtual avatar models overview](https://docs.livekit.io/agents/models/avatar/)
- [OpenAI: new voice models in the API](https://openai.com/blog/advancing-voice-intelligence-with-new-models-in-the-api)
- [Google Places (New) SKU details](https://developers.google.com/maps/billing-and-pricing/sku-details/places)
- [Google Maps Platform India pricing FAQ](https://developers.google.com/maps/billing-and-pricing/india)
- [Twilio India voice guidelines](https://www.twilio.com/en-us/guidelines/in/voice)
- [Synthesia interactive avatar API](https://www.synthesia.io/updates/build-live-avatars-into-your-product-with-interactive-avatar-api)
- [Anam pricing](https://www.anam.ai/pricing)
- [LiveTalking English README](https://github.blesdmm.dns-dynamic.net/lipku/LiveTalking/blob/main/README-EN.md)
- [browser-use on GitHub](https://github.com/Browser-Use/browser-use)
- [Agent Reach English README](https://cdn.jsdelivr.net/gh/Panniantong/Agent-Reach@main/docs/README_en.md)

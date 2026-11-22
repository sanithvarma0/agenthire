# AgentHire: submission

Builders 2026 (OpenAI x Equal AI), Build Creative track. Solo build, 21–22 Nov 2026.

| What | Where |
|---|---|
| Working demo | https://3-213-208-226.sslip.io (test mode: every call rings the builder's phone) |
| Source code | https://github.com/sanithvarma0/agenthire (public; start with the [README](../README.md)) |
| Slides | 5 slides: the problem, what it does, how it works, what's next |

## 1. A working demo on fresh input

The live site runs the whole journey from a new request; nothing is pre-recorded or seeded (its database started empty at deploy).

- **Gig worker:** choose *Gig worker*, pick a language, allow location, add a house number, then talk to the assistant (or type, e.g. "the kitchen tap is leaking"). It finds real providers near you on Google Maps, calls the two you approve, compares their answers and books the one you pick with a confirmation call and an SMS.
- **IT hire:** choose *IT hire*, give a company name and describe a role by voice or typing. Check and approve the job description and questions, wait about 20 seconds for the web crawl, tick up to three candidates and tap *Screen*. The call rings; after it, the shortlist shows each answer scored 1 to 5 with the quote behind it.

Calls are real phone calls (Twilio, through LiveKit). In test mode they all ring the builder, who answers as the provider or the candidate (see section 4).

## 2. Source code

Everything is in the repository above. The README explains the architecture, how to run it, the tests and the evals; `docs/` holds the scope, the designs and the build log with every decision and measurement.

## 3. Evidence of results

All numbers below were measured on 22 Nov 2026 from the app's own database and logs (laptop and live server), or from the eval run in `evals/last_run.md`.

**Real calls, end to end.** 26 phone calls (22 while building on the laptop, 4 on the live server): 15 enquiry calls to providers, 6 booking confirmations and 5 screening calls. Enquiries: 11 providers available, 2 not available, 1 no answer, 1 wanting to speak to the customer directly. All 6 bookings confirmed. Screening: 4 candidates interested, 1 not interested. 10 jobs ran to the end (a booking or a shortlist); the ones that did not finish are shown in History with the reason.

**Grounded results.** After each call a larger model writes the result from the whole transcript, and code checks every fact against the exact line it quotes (numbers against the number said). Across the 26 calls, 70 facts were written and all 70 were confirmed; a fact that fails the check is shown as "not confirmed", never as fact (covered by tests with a made-up quote). The shortlists hold 18 answer scores, each shown only because its quote was found in the transcript. On an earlier call the writer corrected an "available = yes" that the live agent had taken from a greeting.

**Compared with a baseline (live, same builder, same day).**

| Change | Before | After |
|---|---|---|
| End-of-turn wait in the voice brief | LiveKit default (0.3 s): one spoken sentence became 4 turns ("who has around." / "3 years." / "and" / "Some relevant skills in."), each answered, and the brief failed | 1.2 s (3.5 s mid-sentence) and pieces joined: the next brief and two screening calls had no split sentences |
| English speech-to-text | OpenAI `gpt-live-transcribe` (tried as an alternative): transcript 1.1 to 2.9 s after the person stopped, sentences split again, Hindi and Telugu words written in Japanese and Chinese characters | Sarvam `saaras:v4` (code-mixed): transcript 0.2 to 0.4 s after, clean turns; kept |
| Screening call length | 3-minute cap: the first live call was cut while asking the last question | 5 minutes and a goodbye at the cap: the next call covered every question, salary and notice in about 4 minutes |
| Transcript on screen | Each agent line appeared about a second before it was heard | Shown when its voice starts |

**Speed.** Median time from the person stopping to the agent's voice: 3.3 s on the laptop (78 turns), 3.45 s on the live server (41 turns, server in us-east-1 calling speech services in India). This includes a deliberate wait of over a second to be sure the person has finished.

**Evals.** 12 scenarios, 3 runs each, with a larger model playing the provider or candidate: **36 of 36 runs pass** (`evals/last_run.md`, 22 Nov, 11:07, every transcript included). They cover an available electrician, one who asks questions first, one who is fully booked, a voicemail, a Hindi reply to a Telugu call, a wrong number, the booking call (kept and moved), the Telugu and code-mixed voice briefs, and an interested and a not-interested candidate. Each run checks the outcome, every fact's value and date, the call's language and switching, no unprompted mention of being an AI, no characters a voice cannot say, no spoken tool calls, no question asked twice, and a proper ending. The run just before was 33 of 36: all three wrong-number calls ended with an English-only "Thank you, bye" on a Telugu call. One line in the Telugu style file fixed it.

**Tests.** 224 Python tests and 6 web tests, none touching the network.

**Data persists.** SQLite holds jobs, people, conversations, every event, facts and messages (968 events on the laptop, 200 on the server). A job's address (`#/job/<id>`) reopens it at its current step after a reload or on another device, and the History page lists every request with how it ended.

## 4. What I built, what I reused, what is simulated

**Built at the event, by me:** everything specific to AgentHire. The data-driven conversation engine and its kinds (brief, role brief, enquiry call, booking call, screening call), the job flows for both sides, the writers (brief, posting, call result, comparison, scoring), the grounding checks, the dialling and messaging guardrails, the voice worker, the web app and its screens, the evals, and the deploy scripts. I wrote it with AI coding agents (Claude Code), which the rules allow.

**Reused:** my own earlier project SevaMitra (a voice service agent on the same stack) was the reference for the phone setup (Twilio trunk, LiveKit SIP trunks and dispatch), the worker's structure, turn-taking settings and the browser event-stream client; the organisers confirmed that copying from one's own earlier work is allowed. Open-source libraries (LiveKit Agents, FastAPI, React, Vite, Leaflet and others in `pyproject.toml` and `web/package.json`) and these services: OpenAI (conversations, writers, web search), Sarvam (speech to text and voices), Synthesia (real-time avatar), Google Maps Platform (places and addresses), Twilio (phone calls and SMS), LiveKit Cloud, AWS (the event's account).

**Simulated (test mode, on for the demo):**
- Providers are real businesses found on Google Maps, but every call and SMS goes to the builder's own phone, and the builder answers as the provider. Results are labelled "answered by you" and never stored as the provider's own words.
- Candidates are real public profiles found by the web crawl, but they are never contacted: no phone number or email is taken, and each screening call rings the builder, who answers as the candidate.
- The evals use a model playing the provider or candidate.

Nothing else is mocked: the voice brief, the speech, the models, the real phone calls, the writing, the grounding and the shortlist all run for real.

**Data and permission.** Only data I may access: Google Maps results through its API under my key; public web pages read by the web search tool, from which only name, headline, company, location, matching experience and the profile link are kept, for display only; and my own phone number. Nobody found is ever called, messaged or stored with contact details.

**Known limits.** No WhatsApp yet (SMS only). Speech-to-text cannot change language mid-call, so a call that switches between Telugu and Hindi is understood in its starting language. The live server is in the US (the event's AWS account allows only us-east-1 and us-west-2), with about the same speed as the laptop.

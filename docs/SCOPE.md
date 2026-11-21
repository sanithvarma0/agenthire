# AgentHire — Scope

First agreed on Sat 21 Nov 2026, about 1:45 PM IST. Revised about 2:30 PM after the idea was submitted on the event portal, and about 3:10 PM after the tech stack was agreed. Code freeze is Sun 22 Nov, 2:00 PM IST.

## 1. What it is

**Name:** AgentHire

**One line:** a voice assistant that hires people for you, from an electrician to an engineer. You say who you need, it finds people, phones them in their own language, and brings back a shortlist for you to decide.

**Track:** Build Creative (Track 1).

**Two sides on one calling engine:**

- **Home side (blue):** hiring a local tradesperson for a home service.
- **Company side (white):** screening and interviewing job applicants.

The home side is built first. The company side is added on the same engine afterwards.

## 2. What was submitted (locked)

The idea was submitted on the portal and cannot be edited. It promises all of the following, so each one is a "must" in section 9.

**Home side**

- The user says what they need in Telugu or Hindi.
- AgentHire finds real providers nearby.
- After the user approves, it phones each one, says it is an AI calling for a customer, explains the job, and asks whether they can come, when, and what it will cost.
  - **Built differently:** at the builder's request, the agent opens as an ordinary caller. It does not say it is an AI, who it is calling for, or that the call is recorded; it says it is an AI only when asked directly (see section 8). The locked text above still says it announces itself as an AI calling for a customer, so expect the question from judges.
- The user sees the calls as live transcripts, then one comparison of who can come, when and for how much.
- When the user picks one, AgentHire confirms the visit time with that provider and reports the booking back.

**Company side**

- An HR or talent acquisition person describes the role by voice.
- AgentHire writes the job description for approval.
- It phones the applicants for a first screening.
- Shortlisted candidates take a live interview with a real-time AI avatar.
- The hiring team gets a final ranked list with a report on each candidate, where every score quotes what the candidate said.

## 3. Users and problems

| Side | User | Problem |
|---|---|---|
| Home | Older parents who are not comfortable with English or with apps, and anyone else who needs a tradesperson | Finding one means calling four or five numbers, explaining the problem each time, and comparing answers from memory. Parents often depend on a son or daughter in another city to arrange it |
| Company | HR and talent acquisition teams | First-round screening calls take days and ask the same questions every time, and the interviews that follow wait on interviewers' calendars |

## 4. The shared engine

1. **Brief:** the user speaks; the agent asks for anything missing and shows a summary to confirm.
2. **Find:** build a list of people with phone numbers.
3. **Approve:** the user picks who gets called. Nothing is dialled without this.
4. **Call:** the agent phones each person, holds the conversation, and records a structured result.
5. **Report:** a comparison with a recommendation, the transcript and the recording.

The call engine takes its inputs as data: who to call, the language, the goal, the questions to ask, and what it may share. Neither side is written into it.

## 5. Home side

Covers any common home service: electrician, plumber, carpenter, AC repair, appliance repair. The electrician is the main demo.

The flow below was agreed with the builder on Sat 21 Nov, 10:20–10:56 PM.

0. **Start.** The user picks the language (Telugu, Hindi or English) and confirms the address on the same screen: street, colony and area are prefilled from the browser location, and the user adds the house or flat number.
1. **Brief.** A live voice conversation in the browser (LiveKit, the same engine as the calls). The agent speaks first, asking how it can help in the chosen language, collects the service and the work, reads back a short summary and asks the user to confirm. Only then does it search. The user gives no preferred time or budget: providers say when they can come and what they charge, and the user chooses with that in front of them (builder's decision, to keep it simple).
2. **Find.** Real providers from Google Places near the user's location, taken from the browser as Google Maps does it (builder's decision, Sat 21 Nov). Within 5 km, widening to 10 km if fewer than 3 are found. Five that have a phone number are shown on a night map (the user as a blue dot, providers as glowing dots) and as cards. Ranked open-now first, then distance, rating and number of reviews. JustDial and then Urban Company are added afterwards as extra sources, shown side by side with Places for comparison.
3. **Approve.** The top 2 are marked "Calling these 2". The user can swap either one, then taps once to start; nothing is dialled without that tap.
4. **Call.** Real phone calls to those 2, one at a time, in the chosen language, with a live transcript on screen. The user can skip the provider being called or stop the calls. The agent:
   - opens like a local person calling about a problem at home, in two steps as a real call does (builder's decision, Sat 21 Nov): first only a warm greeting and a check that it reached the right shop or person, by name; once they confirm, the colony and locality, the problem in everyday words, and "can you come and check?". If it is the wrong number, it apologises and ends;
   - speaks everyday local Telugu or Hindi (respectful "you" with a friendly "anna" or "bhaiya", warm but not joking), guided by per-language style files with formal-to-natural examples;
   - names the colony and locality from the browser location (the user can correct the colony in the web app);
   - describes the work and the area, and gives the full address if they ask for it;
   - asks whether they can come, when, and the visiting charge;
   - tells them it will confirm shortly (a common thing to say; builder's decision, Sat 21 Nov, 11:00 PM).
5. **Report.** A summary card per provider (can come or not, when, the charge, and their own words), with a recommended pick. The user chooses; the agent does not book the first match on its own.
6. **Confirm.** The agent calls the chosen provider back: says it is the same person who called earlier, confirms the visit at the time they offered, and says the address will follow by message. Then one SMS goes to that provider with the address only. The provider not chosen gets no call and no message. If the confirmation call fails (no answer, or they can no longer come), the screen offers the other provider.
7. **Scheduled.** The screen shows the booking as scheduled: who, when, the charge and the address. It stays in History.

**Call outcomes it must handle:** no answer, busy, wrong number, not available, and "let the customer call me".

**Screens:** English labels; transcripts in whatever the person spoke. A night theme (deep ink background, marigold for actions and the agent's voice, teal for good outcomes, a blue dot for the user), large text and large tap targets, mobile first.

**Memory (should, moved to phase 7):** AgentHire remembers the user's address, language and the providers used before, so a request like "call the same electrician as last time" works.

## 6. Company side

1. **Brief.** Spoken in English. Produces a job description, five screening questions and a scoring guide. The human edits and approves.
2. **Source.** An agent finds real candidates for the role and shows their name, current role, experience and LinkedIn profile link, from a web search of public pages. No LinkedIn scraping and no browser agent (builder's decision, Sun 22 Nov, 3:40 AM): signed out, LinkedIn walls off profiles after a few views; signed in, automation breaks its user agreement; and sourced people are display-only anyway.
3. **Candidates.** The people found by web crawling (step 2). No apply page, form, resume or invite (builder's decisions, Sun 22 Nov, 4:15 to 4:25 AM): the screen works from the approved job description and questions.
4. **Approve.** The human picks who gets a screening call. The crawl takes no phone numbers, so the call rings the builder's own number instead (the demo fallback), and the builder answers as that candidate; its result is labelled as answered by the builder.
5. **Screening call.** By phone, in English, understanding Hindi or Telugu mixed in. Covers interest, the approved questions in priority order, current and expected salary, notice period and location, within 3 minutes (questions not reached are shown as not asked). It opens like the home side: as the company's hiring team, saying it is an AI only if sincerely asked (builder's decisions, Sun 22 Nov, 3:50 AM).
6. **Shortlist.** A ranked list where every score quotes what the candidate said. The human picks who goes to interview.
7. ~~**Avatar interview.**~~ **Dropped** (builder's decision, Sun 22 Nov, 2:40 AM): the company side is phone screening only. The real-time avatar moves to the home side, as the face of the agent taking the user's task in the voice brief.
8. **Final report.** The shortlist from the screening calls is the final ranked list, with the quotes behind each score, for the human to decide.

**Rules for sourced candidates**

- No phone number, email or source page is taken from the web; only name, headline, company, location, a line of matching experience and the profile link.
- So nobody found is ever contacted. A screening call for one rings the builder's number, labelled as answered by the builder, never shown or saved as the real person's own words.
- Naukri and other job-board connectors are future work.

## 7. Languages

| Where | Language |
|---|---|
| Home-side calls | Starts in Telugu or Hindi, chosen before dialling. If the provider answers in the other language, the agent switches to it and stays in it (builder's decision, Sat 21 Nov, 7:12 PM) |
| Screening call | Agent speaks English and understands Hindi or Telugu mixed in |
| Voice brief with the avatar (home side) | The user's chosen language; the avatar lip-syncs to our Sarvam voice |
| Voice brief (home side) | Starts in the language the user picks on the Start screen, then follows whatever the user actually speaks, including mixed Telugu-English or Hindi-English, and a switch mid-conversation |
| Voice brief (company side) | English, understanding Hindi or Telugu mixed in |

**Language mixing** (builder's requirement, Sat 21 Nov, 11:00 PM). People mix languages: Telugu with English words, Hindi with English, or a switch halfway through. The chosen language is only where a conversation starts. Speech is transcribed in Sarvam's code-mixed mode with the language detected per turn, so mixed speech arrives as spoken. On the brief and on provider calls, the agent replies in the language the person is mainly speaking and mixes English words in the way they do; it switches when they keep speaking another language, not on one stray word. If the user picks English but speaks Telugu or Hindi, the brief follows them. Provider calls start in the chosen language (Telugu when the user chose English, since most local tradespeople speak Telugu or Hindi) and follow the provider.

## 8. Rules the agent follows

**On every call**

- **Sounds like a local person calling about a problem at home** (builder's requirement, Sat 21 Nov, 6:15–6:30 PM; this is the core of the product). It greets the tradesperson with the warm, familiar form of address locals use, says where the house is, describes the problem in everyday words, and asks whether they can come and check, all in colloquial speech. It may speak as part of the household ("our house"). It does not introduce itself, say who it is calling for, mention recording, or volunteer that it is an AI.
- Never claims to be human. If someone sincerely asks whether they are talking to a person or a machine, it says it is an AI calling about the job, then carries on.
- Never invents a name. If asked its name, it says the details will follow once they can come, and goes back to the job.
- Dials only numbers the user approved in that session.
- Calls only between 9 AM and 8 PM.
- Names the colony and area when it explains the job, and gives the full address only if the provider asks (builder's decision, Sat 21 Nov, 10:50 PM). Never shares the user's phone number.
- Never agrees to a payment or an advance.
- Ends politely if asked not to call, and does not retry that number.

**On reports**

- Every price, time and candidate quote in a report must appear in the transcript it came from.

**On calling real tradespeople**

- An enquiry about availability and price is fine. The agent confirms a visit only when someone actually wants the work done.
- The first call says the customer will confirm shortly. A provider who is not chosen gets no message (builder's decision, Sat 21 Nov, 10:50–11:00 PM).
- Real calls are kept to a handful, not dozens.
- **Test mode is the demo toggle** (builder's decision, Sat 21 Nov, 7:50 PM). On: providers are found for real, but every call rings the builder's own phone (`DEMO_ROUTE_PHONE`), and the builder plays the provider. Off: the real provider's phone rings, within calling hours. It is on by default.
- A rerouted call is marked as answered by the builder. Its results are never shown or remembered as the real provider's, and nothing from it (a quote, a language, a do-not-call) is saved against the provider's number. The address SMS follows the same toggle.

## 9. Must, should, could, out

| Level | Items |
|---|---|
| **Must** | Home side steps 1–6 with real providers from Google Places and real phone calls; live transcript on screen; company side steps 1–6 and 8 (phone screening, no avatar interview) including candidate sourcing; a real-time avatar for the home-side voice brief; deployed link; README; 4–5 slides; demo recording |
| **Should** | Switching between Telugu and Hindi mid-call when the provider speaks the other language (working in text mode; the voice must switch too in phase 2); memory of the user's preferences; ~~bulk resume upload with a first match score~~ (dropped Sun 22 Nov, 4:15 AM: no resumes); call history page |
| **Could** | JustDial and Urban Company as extra home-side sources; reading LinkedIn profiles signed in; "enter your number and it calls you" for judges; self-hosted avatar backup |
| **Out** | Contacting sourced candidates (their calls ring the builder); apply pages and resumes; Naukri and Indeed; payments; a mobile app; WhatsApp; logins and multiple users |

## 10. Minimum versions

Every "must" was promised in the locked submission, so none can be dropped. If time runs short, each is built in the smallest form that still matches what was submitted.

| Promise | Minimum version |
|---|---|
| Voice brief | One spoken request, one follow-up question at most, then a summary to confirm |
| Find | Top three providers with phone numbers, no ranking beyond rating |
| Calls | One language per call; the five listed outcomes handled; no mid-call language switch |
| Booking confirmation | A confirmation call to the chosen provider and an SMS with the address, both shown on screen |
| Job description | Generated once from the brief, editable in a text box |
| Candidate sourcing | Ten real public profiles from web search alone, with name, headline and link; no browser reading |
| Screening call | Five fixed questions from the approved list, no follow-ups |
| Avatar in the voice brief | One Synthesia avatar lip-synced to our voice; the orb if the avatar does not start |
| Final report | One page per candidate: scores, the quotes behind them, and a rank |

## 11. How it is built

See `TECH_STACK.md`. In short: LiveKit and Twilio for voice, Sarvam for speech, OpenAI for reasoning and writing, a hosted avatar provider, Google Places for providers, web search and a browser agent for candidates, FastAPI and React for the app, and AWS for hosting.

Reusing code from the builder's earlier projects is allowed; the builder confirmed this with the organisers. SevaMitra is the main source, and the README states what was adapted from it.

## 12. First tests

The six tests are listed in `TECH_STACK.md`, section 6. They run once the accounts and keys are set up, which the builder chose to do after the design documents are finished, and before any feature work.

## 13. Timeline

**Superseded.** `BUILD_PLAN.md` holds the current phases, targets, checkpoints and progress, with no sleep block. The table below is the earlier version, kept for the record.

| When | Target |
|---|---|
| Sat 2:30–4 PM | Design documents, repository, keys, and the four first tests |
| Sat 4–8 PM | Call engine holding a Telugu conversation and returning a structured result |
| Sat 8–11 PM | Home side screens: voice brief, find, approve, live transcript, report, confirm |
| Sat 11 PM–midnight | Home side end to end, deployed |
| Sun midnight–3 AM | Company side steps 1–5: brief, job description, apply link, screening call, shortlist |
| Sun 3–6 AM | Sleep |
| Sun 6–9 AM | Avatar interview and final report |
| Sun 9–10:30 AM | Real test calls, failure cases, fixes |
| Sun 10:30 AM–12:30 PM | README, slides, demo recording |
| Sun 12:30–2 PM | Final checks, submission, buffer |

**Checkpoints**

- **Sat midnight:** if the home side is not working end to end, the company side is built in its minimum versions only (section 10).
- **Sun 3 AM:** if the screening call is not working, sleep is shortened before the avatar is.
- **Sun 9 AM:** whatever state the avatar interview is in, feature work stops and testing starts.
- **Sun 10:30 AM:** no code changes except fixes for things found while recording the demo.

## 14. Definition of done

- A person who has never seen it can open the link, speak a request, approve a call, and get a report.
- At least three real home-side calls in Telugu or Hindi are completed and recorded, and one booking is confirmed.
- At least two applicants go through the screening call and the avatar interview, and appear in the final ranked list.
- The repository runs from the README.
- The submission has the repository, a deployed link or recording, and 4–5 slides (the problem, what was built, how it works, what is next).

## 15. Risks

- **The avatar is the least known part.** No provider is chosen and there is no account yet. If the fourth test fails on Saturday, the fallback is a voice interview with a still image, which would fall short of the submitted text.
- **Three promises became "must" after the first scope.** The plan has no slack for a feature that takes twice as long as expected.
- **Real tradespeople may not pick up.** Twilio requires calls into India to come from a non-Indian number, so the caller ID is international.
- ~~**LinkedIn may block the browser agent.**~~ Closed: sourcing is web search only (Sun 22 Nov, 3:40 AM).
- **Setup and tests come after the documents.** If a test fails, the affected document has to be revised.

## 16. Still open

- **Accounts:** LiveKit Cloud, Google Cloud with billing, the event's AWS account and an avatar provider are all to be set up after the design documents.
- **Avatar provider:** not chosen; decided by test.
- **A genuine job for the demo:** if someone actually needs a home service this weekend, a real booking would be the strongest proof.

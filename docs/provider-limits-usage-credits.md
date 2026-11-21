# Provider Limits, Usage & Credits — Consolidated Overview

> One structured reference for all providers. Last updated: **2026-11-21** (Asia/Calcutta).
> Status: **5 providers captured** — OpenAI, Twilio, Sarvam, LiveKit Cloud, Hindsight. Send the next provider's info and it gets added here.
>
> Note on units: OpenAI and Twilio balances are in **USD**; Sarvam shows **platform credits** (currency not displayed on its page); LiveKit is subscription + metered usage (no prepaid balance); Hindsight balance is **USD** (1 credit = $1).

---

## 1. Quick comparison

| Provider | Account / Plan | Balance | Expiring next | Expiry date | Days left | Payment method | Usage captured? |
|---|---|---|---|---|---|---|---|
| OpenAI | Free trial | $250.00 credits | $250.00 | 2027-11-21 | 365 | None on file (not required) | No |
| Twilio | Pay-as-you-go (USD) | $16.71 prepaid | — | — | — | None; auto-recharge not set up | Yes — $3.29 MTD Nov 2026 |
| Sarvam | Free plan, pay-as-you-go billing | 1,378.53 credits | — | — | — | None yet (no payments made) | No |
| LiveKit Cloud | Build plan (project PYTM_VOICE_AGENT) | $0.00 next invoice | — | — | — | Not captured | Yes — Nov 2026, $0.00 total |
| Hindsight | Build org — Inference API + Hindsight Cloud | $43.70 USD credits | — | Not shown (free credits may expire) | — | None saved; auto-recharge needs a card | Partial — ~$11.30 implied spend |

---

## 2. Provider details

### OpenAI (Platform API)

**Account & plan**

- Account status: **Free trial**
- Billing status: not set up yet — payment details must be added before buying credits

**Credits & billing**

- API credit balance: **$250.00**
- Next expiration: **$250.00 on 2027-11-21** (365 days from capture date — low urgency)
- No payment method is required to use the available API credits

**Limits**

- Monthly spend limits: configurable in the console (Usage limits page) — no values captured yet
- Rate limits (RPM/TPM): not captured yet

**Usage**

- Usage to date: not captured yet

**Reference links** (from the billing overview page)

- Credit grants: https://platform.openai.com/settings/organization/billing/credit-grants
- Payment methods: https://platform.openai.com/settings/organization/billing/payment-methods
- Billing history: https://platform.openai.com/settings/organization/billing/history
- Usage limits: https://platform.openai.com/settings/organization/limits
- Pricing: https://openai.com/api/pricing

**Source**: Billing overview page pasted by user on 2026-11-21.

---

### Twilio

**Account & plan**

- Account: "My First Twilio Account" — 1 account, billed in **USD**
- Billing type: **Pay-as-you-go** (prepaid balance)
- Auto-recharge: **not set up**
- All 1 account is billed to this billing group

**Credits & billing**

- Balance: **$16.71**
- Estimated month-to-date spend: **$3.29** (November 2026)
- Historical bills: none yet — the first monthly bill has not been issued

**Usage (November 2026 — estimate, as of capture time)**

- Phone Numbers: quantity 1, spend $0.00
- Elastic SIP Trunking: quantity 65, spend $3.29
- Total: **$3.29**

> Usage summary data is an estimate; actual billed usage appears on the usage statement after month-end.

**Limits**

- Not captured yet

**Source**: Billing overview + usage summary pasted by user on 2026-11-21.

---

### Sarvam (Sarvam API)

**Account & plan**

- Account holder: Sanith Kumar
- Sidebar plan label: **Free plan**; billing page shows **Pay as you go** mode. The console recommends choosing a plan for lower rates and higher limits.

**Credits & billing**

- Credits left: **1,378.53** (platform credits — currency not shown on the page, worth confirming whether these are INR or credits)
- Payments: none yet — transaction history is empty

**Usage**

- Usage dashboard exists but no usage figures captured yet

**Limits**

- Not captured yet

**Source**: Billing page pasted by user on 2026-11-21.

---

### LiveKit Cloud (project PYTM_VOICE_AGENT)

**Account & plan**

- Project: **PYTM_VOICE_AGENT** on LiveKit Cloud, user: Sanith Kumar
- Plan: **Build** — limits are fixed on this plan; upgrading raises them
- Projects draw on the workspace's shared limits; a per-project quota cap is optional (currently off)

**Project limits (Build plan) vs peak usage, past 7 days**

| Type | Limit | Peak usage | Utilization |
|---|---|---|---|
| Server API requests | 1K / min | 6 / 1K | 1% |
| Agents deployed on LiveKit Cloud | 1 | 0 / 1 | 0% |
| Concurrent agent sessions | 5 | 0 / 5 | 0% |
| Hosted agent observations | 10K / min | 0 / 10K | 0% |
| Concurrent participants | 100 | 0 / 100 | 0% |
| Concurrent Egress requests | 2 | 0 / 2 | 0% |
| Total Ingresses | 2 | 0 / 2 | 0% |
| Concurrent Twilio participants | 5 | 0 / 5 | 0% |
| Concurrent WhatsApp participants | 5 | 0 / 5 | 0% |
| Concurrent simulation runs | 30 | 0 / 30 | 0% |
| Simulation runs per minute | 10 | 0 / 10 | 0% |
| Simulation scenario test creations per minute | 10 | 0 / 10 | 0% |

**Inference limits vs peak usage**

| Model | Type | Limit | Peak usage | Utilization |
|---|---|---|---|---|
| LiveKit Turn Detector v1 (livekit/turndetector-v1) | TD | 5 concurrent connections | 2 / 5 | **40%** |
| LiveKit Turn Detector v1 | TD | 45 requests / min | 8 / 45 | 18% |
| LiveKit Turn Detector v1 | TD | 7.5K requests / month | 524 / 7.5K | 7% |
| LiveKit Adaptive Interruption (livekit/bargein) | INT | 40K requests / month | 119 / 40K | <1% |

**Credits & billing**

- Billing model: plan subscription + metered usage (no prepaid balance)
- Next invoice: **$0.00**
- Statements: none yet — statements appear after the first payment is processed
- Bandwidth: 0 MB today; 1 GB in November 2026

**Usage (November 2026 — all within included Build quotas, total $0.00)**

| Included quota | Used | Cost |
|---|---|---|
| Third-party SIP minutes (1,000 incl.) | 51 min | $0.00 |
| WebRTC participant minutes (5,000 incl.) | 135 min | $0.00 |
| Downstream data transfer (50 GB incl.) | 1 GB | $0.00 |
| Additional downstream transfer ($0.00/GB) | 0 GB | $0.00 |
| Observability logs (100,000 incl.) | 51,065 | $0.00 |
| Observability spans (100,000 incl.) | 5,868 | $0.00 |
| Observability transcripts (100,000 incl.) | 1,279 | $0.00 |
| Observability audio minutes (1,000 incl.) | 81 min | $0.00 |
| Barge-in self-hosted requests (40,000 incl.) | 119 | $0.00 |
| Krisp background minutes (100 incl.) | 20 min | $0.00 |
| EOT self-hosted requests (7,500 incl.) | 524 | $0.00 |

**Source**: Usage-and-limits + Billing pages pasted by user on 2026-11-21.

---

### Hindsight (Inference API / Hindsight Cloud)

**Account & plan**

- Organization: "sanith's Organization" — sidebar plan label: **Build**
- Products: Inference API + Hindsight Cloud — **one credit balance covers both** ("Shared with Hindsight Cloud")

**Credits & billing**

- Available balance: **$43.70 USD** (1 credit = $1 USD; payments via Stripe)
- Free credits applied — their expiry date is not shown on the page
- Billing information (name / email / address / VAT ID): **not set**
- Payment methods: none saved; auto-recharge cannot be enabled until a card is added
- Invoices: none yet
- Top-up options: $10 Starter / $25 Basic / $50 Standard / $100 Pro, or custom $5–$1,000; sales contact for volume pricing above $5,000 in 12 months

**Implied spend to date (derived from transaction history)**

- Total credits granted: **$55.00** — $5.00 welcome grant (GitHub star claim) + $50.00 promo code MEMHACK99
- Balance decline implies **~$11.30 consumed**: $2.20 between the Sep 28 grant and the Sep 29 promo transaction, then $9.10 after it ($52.80 → $43.70)
- Caveat: part of the decline could be free-credit expiry rather than API usage; only these 2 transactions were visible in the history

**Transaction history**

| Date | Type | Description | Amount | Balance after |
|---|---|---|---|---|
| Sep 28, 9:12 PM | grant | Welcome credits (GitHub star claim) | +$5.00 | $5.00 |
| Sep 29, 12:41 AM | promo | Promo code MEMHACK99 | +$50.00 | $52.80 |

**Rates (Inference API)**

| Model | Price |
|---|---|
| hs-decide-1-flash | $0.02 / 1M input tokens |
| hs-rerank-1 | $0.015 / 1M input tokens |
| hs-embed-1 | $0.005 / 1M input tokens |

**Limits**

- Not captured yet (no rate limits shown on the billing page)

**Source**: Billing page pasted by user on 2026-11-21.

---

## 3. Watch items

| Priority | Provider | Item |
|---|---|---|
| Medium | Twilio | Prepaid balance **$16.71** with auto-recharge not set up — service stops if it hits $0. Spend is modest so far ($3.29 in Nov 2026), but Elastic SIP Trunking usage can scale quickly; consider enabling auto-recharge. |
| Medium | Sarvam | **1,378.53 credits** left and no payments yet. Burn rate unknown — check the usage page to estimate runway, and add credits or pick a plan before they run out. |
| Medium | Hindsight | **$43.70** left from $55.00 in free credits (~$11.30 already consumed). No card saved and auto-recharge unavailable until one is added; free-credit expiry date unknown. |
| Low | LiveKit | Turn Detector concurrent connections peaked at **2/5 (40%)** in the past 7 days — the tightest Build-plan limit. Everything else under 20%; November usage all within included quotas, invoice so far $0.00. |
| Low | OpenAI | $250.00 credits expire 2027-11-21 (365 days out). No payment method on file — add one before buying credits or once usage starts. |

---

## Appendix: data capture template

Use this structure when sending the next provider's info (any format is fine — I'll normalize it):

```
Provider:
Account/Plan:
Credit balance:
Expiring amount + date:
Payment method:
Usage to date:
Limits (rate/daily/monthly):
Notes:
```

# TakeKash as a Product — Scoping Brief

*What's already real, what's missing, and how the "digital + physical" idea splits into two very different projects.*

## You've already started this

takekash.com isn't just a landing page for your own clips — it's already built as the marketing site for **TakeKash**, an "AI Clipping Agent for Twitch & YouTube Streamers," with three pricing tiers (Free / Creator $19/mo / Pro $49/mo) and real Stripe price IDs already created (`price_1TusrSEzp7cPN80JFqijvMhd` for Creator, `price_1TusqeEzp7cPN80JyfdJhJSJ` for Pro). There's also a "Command Center" chat-style page and a "Job Status" table already mocked up in the UI.

The pipeline repo also already has the start of real multi-user infrastructure:

- `lib/saas_auth.py` — real PBKDF2-HMAC-SHA256 password hashing (200,000 iterations), not a placeholder.
- `lib/saas_billing.py` — a real Stripe integration, but built around **pay-per-clip credits**.
- `lib/saas_db.py` — a real SQLite layer for multi-user accounts and credits.

So the "sellable product for other streamers" idea isn't starting from zero. It's starting from a marketing site and some backend scaffolding that don't yet agree with each other or connect to anything live.

## The gap that matters most: two different pricing models

The site sells **flat monthly subscriptions** ($19/mo, $49/mo). The billing code implements **pay-per-clip credits**. Those are genuinely different products from a customer's perspective — one is "unlimited within your tier," the other is "you pay for what you use." This needs a real decision before either the checkout button or the billing code can be finished, because building out either path halfway will need to be redone if you pick the other.

## What's missing for a real multi-tenant launch (software side)

1. **Multi-tenant pipeline.** Right now the pipeline is tuned for one channel — one watermark asset, one set of platform credentials, output paths that assume a single user. A real product needs per-customer isolation: their own watermark/branding, their own connected TikTok/YouTube/Instagram accounts, their own job queue.
2. **Real checkout.** `startCheckout()` on the pricing page already calls `/api/create-checkout-session` — that endpoint doesn't exist yet. No Netlify Functions were deployed on this site before today.
3. **Cloud-hosted processing.** The pipeline currently runs locally on your Mac. Customers won't have access to that — clip generation needs to run on infrastructure you host, not your personal machine.
4. **Onboarding flow.** Signup, connecting a customer's own streaming/social accounts, and getting their source video (VOD link or upload) into the pipeline.
5. **Command Center / Job Status going from mockup to real.** Both already have UI; neither is wired to real per-customer data yet.

None of this is a good problem to have this week — it's a real second product, not a feature. It's buildable with code, but it's a project on the scale of what the admin dashboard was, several times over.

## The physical display — a different kind of project

A physical hardware display (however you're picturing it — a small screen, a stream-deck-style device, a branded piece of hardware) is not something code tools can scope or build. It needs:

- Real unit economics (cost to manufacture + ship vs. what a streamer would pay).
- Industrial design and a manufacturing/sourcing partner.
- Its own go-to-market decision: is it a companion product, a premium bundle add-on, or its own thing entirely.

**Recommendation:** keep this fully separate from the software launch. Don't let it block or slow down getting the digital product to a sellable state. If you want, the natural next step here is a short vendor/feasibility pass (comparable products, rough manufacturing cost ranges, MOQs) once the software side has real customers to gauge actual demand against — building hardware speculatively, before you know streamers want it, is the highest-risk part of this idea.

## Suggested order of operations

1. Decide: flat subscription or pay-per-clip credits (or both, as separate tiers) — this unblocks everything else.
2. Wire real Stripe checkout for whichever model you pick.
3. Scope multi-tenant pipeline isolation (this is the biggest software lift).
4. Wire Command Center / Job Status to real per-customer data.
5. Physical hardware stays parked until 1–4 are live and you have real signal from actual streamers.

Say the word on the pricing-model decision and I'll start on whichever of these you want to tackle first.

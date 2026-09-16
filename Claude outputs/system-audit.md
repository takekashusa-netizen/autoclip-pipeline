# Full-System Audit — What Else Is Needed

*Everything found while working across the pipeline, the site, and the admin dashboard. Ordered by urgency, not by when it was found.*

## 1. Security — do this first

**Your YouTube OAuth credentials are committed to git.** `youtube_client_secret.json` and `youtube_token.pickle` are both tracked in `autoclip-pipeline` (confirmed via `git ls-files` and commit history — they've been in at least one real commit, not just sitting locally) and the repo's remote is `github.com/takekashusa-netizen/autoclip-pipeline`. I couldn't confirm from here whether that repo is public or private (GitHub access needs your approval to fetch), but the standard move once a credential has been committed is to **rotate it regardless** — removing the file going forward doesn't erase it from git history. Concretely: revoke/regenerate the OAuth client in Google Cloud Console, re-auth, replace the token file, and add both filenames to `.gitignore` (they currently aren't covered — your `.gitignore` only excludes `skills/publish/client_secret.json` and `skills/publish/youtube_token.json`, different paths than the ones actually tracked at the repo root).

**When you complete the TikTok OAuth flow (see #2), `tiktok_token.json` will land at the repo root too, and it is not in `.gitignore` either.** Add it before you run `lib/tiktok_oauth_flow.py`, not after, so it never gets committed in the first place.

**The admin dashboard's `ADMIN_KEY`** is generated and documented in `ADMIN-SETUP.txt` but hasn't been added to Netlify yet — the dashboard won't actually work until you do that step.

## 2. Your TikTok/Instagram content can't actually post yet

I checked the live publish queue (`publish_schedule.json` — the one that's real, not the DB mirror described in #4) rather than assume. It has 104 pending + 21 approved items, and the 2 that have already come due both failed with the same root causes:

- **TikTok**: no OAuth token exists (`tiktok_token.json` was never created). One-time fix: register the redirect URI `https://takekash.com/oauth-callback` in your TikTok app's Login Kit, set `TIKTOK_CLIENT_KEY`/`TIKTOK_CLIENT_SECRET`, then run `python3 lib/tiktok_oauth_flow.py` once.
- **Instagram**: `INSTAGRAM_ACCESS_TOKEN`/`INSTAGRAM_USER_ID` aren't set, **and** even once they are, there's a deeper architectural gap — Instagram's API requires a publicly-reachable URL for each video; it does not accept direct upload from your machine the way YouTube and TikTok do. This pipeline only produces local files right now. You'll need some form of public video hosting (S3/R2/Netlify itself/etc.) in the publish path before Instagram posts can go out at all — that's real, separate infrastructure, not a config toggle. Also, the Meta app review for `instagram_business_content_publish` typically takes 2–4 weeks, so this is the longest lead-time item in this whole list if you haven't started it yet.

Bottom line: every TikTok/Instagram item queued this month (72 of them, from the judge-show batch) will fail the same way as they come due, until these are addressed. Worth doing before more get queued.

## 3. A month of real work is sitting uncommitted

Last commit on `autoclip-pipeline` was **2026-08-14** ("add SaaS foundation..."). Everything since — the watermarking feature, the `ass_caption_burner.py` performance fix, `publish_scheduler.py` changes, the admin snapshot exporter, all of it — is uncommitted local changes with no history and no backup on GitHub. Also: there's a stale `.git/index.lock` file that blocked a git command when I checked (may be a quirk of this sandboxed environment rather than your real Mac — worth checking `git status` in your actual Terminal to confirm it isn't stuck there too, since a leftover lock file can block all future commits until removed).

Separately, minor hygiene: `dashboard.log`, `watch.log`, and `logs/doctor_auto_resume.log` are tracked in git and show as modified — log files generally shouldn't be committed at all (they churn constantly and bloat history). Worth adding to `.gitignore` alongside the token files above.

## 4. The database can't be trusted for content-safety questions — and that question is still open

`takekash.db`'s `social_posts` table shows 9 YouTube rows marked `blocked`, with a note that they were retroactively flagged by a "content-safety audit" for being judge/court-show content miscategorized as gaming. But this table is a write-only mirror that the live pipeline never reads back — it's bookkeeping, not a live reflection of what's actually on YouTube (all 9 rows have no `platform_post_id`, so there's no way to check from the DB alone which real video they refer to). This is the exact open question from before (task: "audit DB published status against real YouTube content") — it's still unresolved, and it's the only way to actually know whether any non-gaming content is currently live on the real GtaxZombies channel. Worth prioritizing if channel content strategy/brand consistency matters to you.

## 5. Storage is growing with no cleanup policy

`outputs/` is 7.1GB and climbing (`gtaxlong1_best_windows` alone is 2.6GB). No archival or cleanup step exists in the pipeline once clips are published. Worth deciding a policy — e.g., delete or move-to-cold-storage renders older than N days past their publish date — before this becomes a real disk problem.

## 6. Already-known, still open

- Populate the `analytics` table with real YouTube stats via `fetch_youtube_stats.py` — has to run directly on your Mac (not through this session's sandboxed bridge), since `oauth2.googleapis.com` isn't reachable from there.
- The recurring "optimizing data specialist" system depends on the above.
- The pricing-model conflict (flat subscription vs. pay-per-clip credits) from the product brief — still unresolved, still blocking real Stripe checkout work.

## Suggested order

1. Rotate the YouTube credentials and fix `.gitignore` (today — costs nothing to delay it).
2. Commit the last month of work before anything else touches these repos.
3. Decide the TikTok/Instagram path — at minimum finish TikTok OAuth (cheap), and decide whether Instagram is worth the hosting build-out + review wait right now or should wait.
4. Set `ADMIN_KEY` in Netlify and deploy, so the dashboard you already have actually comes online.
5. Everything else in this list can wait for a normal work session.

# SEO & Hashtag Strategy — Platforms + Games

Real, sourced research (2026-09-23) into current TikTok/Instagram/YouTube SEO
practices and per-game trending hashtags for everything this pipeline
produces. Backs the `GAME_KEYWORD_TAXONOMY` in `lib/generate_clip_metadata.py`
(which now reflects this). Nothing here is guessed — every number/tag traces
to a source at the bottom.

## Platform-level rules (apply regardless of game)

- **TikTok**: 3-5 hashtags per post, not the max 5. Mix ~1-2 broad/trending
  tags with 2-3 niche ones. On-screen text and keyword-rich captions now
  weight as heavily as hashtags for discoverability. First 3 seconds of the
  video is the single biggest factor in whether it gets past the scroll.
  Completion rate / watch time is now the strongest FYP ranking signal —
  rewards full-watch or replayed clips over just likes/shares.
- **Instagram Reels**: same 3-5 hashtag range, but treat it as "does this tag
  earn its place" — cut anything that isn't directly relevant. Put hashtags
  in the caption itself, not a comment (Instagram reads caption metadata at
  publish time).
- **YouTube Shorts**: broad tags (#Gaming, #Gameplay) still pull the most raw
  volume, but niche tags often out-perform on a views-per-post basis (e.g.
  #GamingTips beat most high-volume tags in views-per-clip despite far fewer
  clips using it). Combine one broad + one niche rather than stacking broad
  tags only.

## Per-game hashtags (real relevance-ranked or usage-ranked data)

### Apex Legends
| Tag | Why |
|---|---|
| #ApexLegends | Base tag, 100% relevance anchor |
| #Apex | 34% relevance to #ApexLegends |
| #ApexLegendsClips | Strongest *similar* tag — 574,584 Instagram posts |
| #Gaming | 30.7% relevance, high broad reach |
| #Twitch | 28% relevance — pulls in streaming audience specifically |
| #FPS | Genre tag, real usage in gaming-clip data |
| #BattleRoyale | Genre tag |
| #ApexRanked | Niche/competitive angle |

### Call of Duty: Warzone (newly added — wasn't in the taxonomy before, despite being one of the 3 games on stream)
| Tag | Why |
|---|---|
| #Warzone | Direct tag |
| #CallOfDutyWarzone | Most similar tag, 119,269 posts |
| #CallOfDuty / #COD | 51.7% / 41.6% relevance — by far the strongest related tags |
| #ModernWarfare | 25.9% relevance |
| #Gaming, #FPS, #Twitch | Same broad/genre/streaming logic as Apex |

### NBA 2K26
Existing tag set (#NBA2K26, #2K26, #NBA2K, #Build, #Jumpshot, #ShootingGuard,
#MyCareer, #Gaming) confirmed active and correctly targeted — #2k26 is a real,
current tag. No change made; didn't find evidence any swap would outperform
what's already there.

### EA Sports FC 26
| Tag | Why |
|---|---|
| #FC26, #EAFC26 | Confirmed active, current tags |
| #EAFC | Added — shorter/broader real tag, same community |
| #UltimateTeam, #FUT, #Rush, #Clubs | Mode-specific, keep as-is |

### Brawlhalla
**Real finding, changed the taxonomy:** the generic `#Brawl` tag is actually
dominated by *Brawl Stars* (a different, unrelated game) — ~800K posts vs.
Brawlhalla's own 59,550 under that tag. Using `#Brawl` was putting these
clips in front of the wrong audience. Dropped it; kept `#Brawlhalla` itself
(the real, correctly-targeted tag) plus the mode/genre tags.

## Sources
- [Top 250 TikTok Hashtags for 2026 — Buffer](https://buffer.com/resources/tiktok-hashtags/)
- [50+ Gaming TikTok Hashtags 2026 — OpusClip](https://www.opus.pro/research/best-hashtags-gaming-tiktok)
- [50+ Gaming YouTube Hashtags 2026 — OpusClip](https://www.opus.pro/research/best-hashtags-gaming-youtube)
- [Instagram Reel Hashtags — Sprout Social](https://sproutsocial.com/insights/instagram-reel-hashtags/)
- [#apexlegends hashtag data — Display Purposes](https://displaypurposes.com/hashtags/hashtag/apexlegends)
- [#warzone hashtag data — Display Purposes](https://displaypurposes.com/hashtags/hashtag/warzone)
- [#brawl hashtag data — Display Purposes](https://displaypurposes.com/hashtags/hashtag/brawl)
- [How the TikTok algorithm works in 2026 — Hootsuite](https://blog.hootsuite.com/tiktok-algorithm/)

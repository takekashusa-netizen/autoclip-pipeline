/* TakeKash SEO Studio — generation engine (client-side, no API keys).
   Platform limits verified Nov 2026:
   YouTube: title 100 (≈60-70 visible), desc 5000, tags 500 total, ≤15 hashtags (first 3 show above title)
   Shorts: same hard limits, ≈40 chars of title visible in feed
   TikTok: caption 4000, 3-5 hashtags recommended
   Instagram: hard cap 5 hashtags per post/Reel (since Dec 18 2025)
   Twitch: title 140, 10 tags, ≤25 chars, letters/numbers only, no spaces
   Google: title ≈60 chars, meta description ≈155-160 */
(function (root) {
  'use strict';
  var YEAR = new Date().getFullYear();
  var MONTH = ['January','February','March','April','May','June','July','August','September','October','November','December'][new Date().getMonth()];

  var PLATFORMS = {
    youtube:   { label: 'YouTube',        titleMax: 100, titleVisible: 65, descMax: 5000, tagBudget: 500, hashtags: 3,  hashMax: 15 },
    shorts:    { label: 'YouTube Shorts', titleMax: 100, titleVisible: 40, descMax: 5000, tagBudget: 500, hashtags: 4,  hashMax: 15 },
    tiktok:    { label: 'TikTok',         titleMax: 150, titleVisible: 70, descMax: 4000, hashtags: 5, hashMax: 5 },
    instagram: { label: 'Instagram',      titleMax: 125, titleVisible: 125, descMax: 2200, hashtags: 5, hashMax: 5 },
    twitch:    { label: 'Twitch',         titleMax: 140, titleVisible: 60, descMax: 300, twitchTags: 10 },
    website:   { label: 'Website / Google', titleMax: 60, titleVisible: 60, descMax: 160, descMin: 140 }
  };

  var STOP = 'a an the and or of for to in on at with my your our this that is are was be it its i me we you how what why best top new vs video videos clip clips'.split(' ');

  /* ---------- Category taxonomy ---------- */
  var CATS = {
    gaming: { label: 'Gaming', broad: ['gaming','gamer','video games','gameplay','gaming community','gaming clips','pc gaming','console gaming','ps5','xbox','streamer','gaming highlights'],
      hash: ['gaming','gamer','gameplay','gamingclips','videogames'], twitch: ['Gaming','Chill','PlayingWithViewers','Competitive'],
      audience: 'gamers', cta: 'Like + subscribe for more gameplay and clips every week.', kw: 'gaming|gamer|gameplay|fps|battle royale|loadout|ranked|stream|streamer|clutch|controller|ps5|xbox|nintendo|esports' },
    tech: { label: 'Tech & Software', broad: ['technology','tech','tech review','software','ai tools','apps','productivity tools','tech tips','gadgets','artificial intelligence'],
      hash: ['tech','technology','aitools','software','techtok'], twitch: ['Tech','Software','AI','Creators'],
      audience: 'creators and tech fans', cta: 'Subscribe for more tools that save you time.', kw: 'ai|app|software|tool|saas|tech|gadget|phone|iphone|android|laptop|pc build|coding|automation|clipping|editor|editing' },
    business: { label: 'Business & Marketing', broad: ['business','entrepreneur','small business','marketing','side hustle','make money online','startup','digital marketing','business tips','brand'],
      hash: ['business','entrepreneur','smallbusiness','marketing','sidehustle'], twitch: ['Business','Entrepreneur','Marketing'],
      audience: 'entrepreneurs and creators', cta: 'Follow for more business moves you can use today.', kw: 'business|commercial|ad |ads|marketing|brand|startup|entrepreneur|hustle|sales|ecommerce|dropship|shopify|fiverr|agency|service|client' },
    creator: { label: 'Content Creation', broad: ['content creator','content creation','youtube tips','tiktok tips','video editing','short form content','creator economy','grow on youtube','social media growth','streaming'],
      hash: ['contentcreator','creatortips','videoediting','shortformcontent','contentcreation'], twitch: ['ContentCreation','Creator','Editing'],
      audience: 'creators', cta: 'Follow for creator tips that actually move the needle.', kw: 'creator|content|editing|edit|thumbnail|youtube growth|grow|subscribers|views|viral|shorts|reels|overlay|obs|stream setup' },
    music: { label: 'Music', broad: ['music','new music','hip hop','rap','beats','music producer','independent artist','songs','music video','playlist'],
      hash: ['music','newmusic','hiphop','musicproducer','independentartist'], twitch: ['Music','MusicProduction','Beats'],
      audience: 'music fans', cta: 'Stream it, share it, and subscribe for new drops.', kw: 'music|song|beat|rap|hip hop|album|single|producer|lyrics|remix|freestyle' },
    sports: { label: 'Sports', broad: ['sports','basketball','football','nba','nfl','sports highlights','athlete','sports news','game highlights','fantasy sports'],
      hash: ['sports','nba','nfl','basketball','sportshighlights'], twitch: ['Sports','Basketball','Football'],
      audience: 'sports fans', cta: 'Subscribe for more highlights and breakdowns.', kw: 'nba|nfl|basketball|football|soccer|baseball|dunk|touchdown|athlete|playoffs|draft' },
    fitness: { label: 'Fitness & Health', broad: ['fitness','workout','gym','exercise','health','weight loss','home workout','fitness motivation','strength training','wellness'],
      hash: ['fitness','workout','gym','fitnessmotivation','health'], twitch: ['Fitness','Workout'],
      audience: 'people who train', cta: 'Save this for your next session and follow for more.', kw: 'fitness|workout|gym|exercise|lift|cardio|abs|muscle|yoga|run|diet' },
    food: { label: 'Food & Cooking', broad: ['food','cooking','recipe','easy recipes','home cooking','foodie','dinner ideas','meal prep','baking','food review'],
      hash: ['food','cooking','recipe','foodie','easyrecipes'], twitch: ['Cooking','Food'],
      audience: 'home cooks', cta: 'Save the recipe and follow for more easy meals.', kw: 'food|cook|recipe|meal|bake|kitchen|dinner|lunch|breakfast|grill|bbq|restaurant' },
    beauty: { label: 'Beauty & Fashion', broad: ['beauty','makeup','skincare','fashion','style','outfit ideas','hair','grwm','beauty tips','streetwear'],
      hash: ['beauty','makeup','skincare','fashion','style'], twitch: ['Beauty','Fashion'],
      audience: 'style lovers', cta: 'Follow for more looks and honest picks.', kw: 'makeup|skincare|beauty|fashion|outfit|style|hair|nails|sneaker|streetwear|grwm' },
    education: { label: 'Education & How-To', broad: ['education','tutorial','how to','learn','tips and tricks','explained','guide','study','online learning','life hacks'],
      hash: ['learnontiktok','tutorial','howto','education','tips'], twitch: ['Educational','Tutorial'],
      audience: 'learners', cta: 'Subscribe for more step-by-step guides.', kw: 'learn|tutorial|lesson|explained|guide|course|study|teach|class' },
    finance: { label: 'Finance & Money', broad: ['personal finance','money','investing','stocks','trading','financial freedom','passive income','budgeting','credit','wealth'],
      hash: ['finance','money','investing','trading','personalfinance'], twitch: ['Trading','Finance','Stocks'],
      audience: 'people building wealth', cta: 'Follow for more money moves. Not financial advice.', kw: 'money|invest|stock|trading|crypto|futures|finance|credit|budget|wealth|income' },
    comedy: { label: 'Comedy & Entertainment', broad: ['funny','comedy','entertainment','memes','funny videos','skits','pranks','viral videos','reaction','try not to laugh'],
      hash: ['funny','comedy','memes','funnyvideos','entertainment'], twitch: ['Comedy','JustChatting','Funny'],
      audience: 'everyone', cta: 'Send this to someone who needs a laugh.', kw: 'funny|comedy|meme|prank|skit|laugh|reaction|roast' },
    podcast: { label: 'Podcast & Interviews', broad: ['podcast','podcast clips','interview','talk show','conversation','podcast episode','storytime','motivation','advice','real talk'],
      hash: ['podcast','podcastclips','interview','podcasting','storytime'], twitch: ['Podcast','JustChatting','TalkShow'],
      audience: 'podcast listeners', cta: 'Watch the full episode and subscribe for more clips.', kw: 'podcast|interview|episode|talk show|guest|conversation|news' },
    auto: { label: 'Cars & Automotive', broad: ['cars','car review','automotive','car culture','car mods','supercars','car tips','trucks','detailing','new cars'],
      hash: ['cars','carsoftiktok','carculture','automotive','carmods'], twitch: ['Cars','Automotive'],
      audience: 'car enthusiasts', cta: 'Subscribe for more builds and reviews.', kw: 'car|truck|engine|drift|mod|detailing|tesla|bmw|mustang|exhaust' },
    home: { label: 'Home, DIY & Products', broad: ['home improvement','diy','product review','amazon finds','home security','gadgets','smart home','unboxing','must have products','home tips'],
      hash: ['diy','amazonfinds','homeimprovement','productreview','smarthome'], twitch: ['DIY','Makers'],
      audience: 'homeowners and DIYers', cta: 'Follow for more finds that are worth it.', kw: 'diy|home|solar|camera|security|amazon|unboxing|product|gadget|lamp|light|smart home' },
    travel: { label: 'Travel & Lifestyle', broad: ['travel','lifestyle','vlog','day in my life','travel tips','adventure','explore','vacation','city guide','daily vlog'],
      hash: ['travel','lifestyle','vlog','dayinmylife','traveltips'], twitch: ['IRL','Travel','Vlog'],
      audience: 'travelers', cta: 'Follow along for the next stop.', kw: 'travel|trip|vlog|vacation|city|hotel|flight|day in my life|lifestyle|texas' }
  };

  /* ---------- Known entities (expand freely) ---------- */
  var ENTITIES = [
    { re: /\bwar ?zone\b/, cat: 'gaming', name: 'warzone', rel: ['call of duty','cod warzone','warzone highlights','warzone best loadout','warzone tips','battle royale','fps games','cod clips'], twitch: ['Warzone','CallOfDuty','BattleRoyale'] },
    { re: /\b(mw4|modern warfare (4|iv))\b/, cat: 'gaming', name: 'modern warfare 4', rel: ['mw4','call of duty','mw4 gameplay','mw4 best class','mw4 multiplayer','cod multiplayer','fps games'], twitch: ['MW4','CallOfDuty','FPS'] },
    { re: /\bblack ops\b/, cat: 'gaming', name: 'black ops', rel: ['call of duty','black ops gameplay','cod zombies','cod multiplayer'], twitch: ['BlackOps','CallOfDuty'] },
    { re: /\b(call of duty|cod)\b/, cat: 'gaming', name: 'call of duty', rel: ['cod','cod clips','cod gameplay','fps games','cod multiplayer'], twitch: ['CallOfDuty','COD'] },
    { re: /\bapex( legends)?\b/, cat: 'gaming', name: 'apex legends', rel: ['apex','apex highlights','apex ranked','apex legends tips','battle royale','apex movement','fps games'], twitch: ['ApexLegends','Apex','BattleRoyale'] },
    { re: /\b(nba ?2k ?\d*|2k ?2\d)\b/, cat: 'gaming', name: 'nba 2k' , rel: ['2k','nba 2k27','2k27','2k park','2k rec','best jumpshot','myteam','basketball game'], twitch: ['NBA2K27','2K','BasketballGame'] },
    { re: /\bfortnite\b/, cat: 'gaming', name: 'fortnite', rel: ['fortnite clips','fortnite tips','battle royale','fortnite zero build','fortnite season'], twitch: ['Fortnite','BattleRoyale'] },
    { re: /\b(gta ?(6|vi|5|v|online)?|grand theft auto)\b/, cat: 'gaming', name: 'gta', rel: ['gta 6','gta online','grand theft auto','rockstar games','open world games'], twitch: ['GTA','GTAOnline','Roleplay'] },
    { re: /\bminecraft\b/, cat: 'gaming', name: 'minecraft', rel: ['minecraft builds','minecraft survival','minecraft tips','minecraft funny'], twitch: ['Minecraft','Survival'] },
    { re: /\bvalorant\b/, cat: 'gaming', name: 'valorant', rel: ['valorant clips','valorant tips','valorant ranked','tactical shooter'], twitch: ['Valorant','FPS'] },
    { re: /\broblox\b/, cat: 'gaming', name: 'roblox', rel: ['roblox games','roblox funny','roblox obby'], twitch: ['Roblox'] },
    { re: /\b(ea fc|fc ?2\d|fifa)\b/, cat: 'gaming', name: 'ea fc', rel: ['ea sports fc','fc ultimate team','fifa','soccer game'], twitch: ['EAFC','UltimateTeam'] },
    { re: /\bmadden\b/, cat: 'gaming', name: 'madden', rel: ['madden nfl','madden ultimate team','football game'], twitch: ['Madden','MUT'] },
    { re: /\brocket league\b/, cat: 'gaming', name: 'rocket league', rel: ['rocket league clips','rocket league ranked','car soccer'], twitch: ['RocketLeague'] },
    { re: /\btwitch\b/, cat: 'creator', name: 'twitch', rel: ['twitch streamer','twitch clips','live streaming','grow on twitch','small streamer'], twitch: ['SmallStreamer','Twitch'] },
    { re: /\bobs\b/, cat: 'creator', name: 'obs', rel: ['obs studio','stream setup','obs tutorial','streaming setup'], twitch: ['OBS','StreamSetup'] },
    { re: /\boverlay/, cat: 'creator', name: 'stream overlay', rel: ['twitch overlay','stream alerts','obs overlay','stream design','streamer setup'], twitch: ['Overlay','StreamSetup'] },
    { re: /\b(clipping|auto ?clip|ai clip|clipper)/, cat: 'tech', name: 'ai clipping', rel: ['ai video clipping','auto clip generator','stream clips','short form video','clip maker','repurpose content','vertical video'], twitch: ['Clips','AI'] },
    { re: /\btakekash\b/, cat: 'tech', name: 'takekash', rel: ['takekash app','takekash ai','ai clipping tool','clip generator for streamers'], twitch: ['TakeKash'] },
    { re: /\b(commercial|advert|ad spot|promo video)\b/, cat: 'business', name: 'commercial', meta: true, rel: ['brand commercial','product ad','video ad','promo video','advertisement'], twitch: [] },
    { re: /\bsolar\b/, cat: 'home', name: 'solar', rel: ['solar panel','solar powered','off grid','solar camera'], twitch: [] },
    { re: /\b(security camera|doorbell cam)/, cat: 'home', name: 'security camera', rel: ['home security','outdoor camera','wireless security camera','camera setup'], twitch: [] },
    { re: /\bfutures|tradovate|nq\b|mnq\b/, cat: 'finance', name: 'futures trading', rel: ['day trading','nasdaq futures','trading strategy','prop firm'], twitch: ['DayTrading','Futures'] },
    { re: /\bfiverr\b/, cat: 'business', name: 'fiverr', rel: ['fiverr gig','freelancing','freelance services','make money on fiverr'], twitch: [] }
  ];

  /* ---------- Content intent ---------- */
  var INTENTS = [
    { id: 'highlights', re: /\b(montage|highlights?|best moments|plays|clutch|kills?|wins?|compilation)\b/, words: ['highlights','best moments','clips','montage','top plays','compilation'] },
    { id: 'howto',      re: /\b(how to|tips?|guide|tutorial|learn|beginners?|tricks?|explained|setup guide|step by step)\b/, words: ['tips','guide','tutorial','tips and tricks','for beginners','how to'] },
    { id: 'review',     re: /\b(review|unboxing|vs\.?|versus|comparison|worth it|tested|honest)\b/, words: ['review','unboxing','honest review','worth it','comparison'] },
    { id: 'funny',      re: /\b(funny|fails?|memes?|prank|laugh|troll|rage)\b/, words: ['funny moments','fails','funny','memes','try not to laugh'] },
    { id: 'setup',      re: /\b(loadout|build|class|settings|setup|meta|config|sensitivity)\b/, words: ['best loadout','meta','settings','best build','setup'] },
    { id: 'live',       re: /\b(live|stream(ing)?|grind|subathon)\b/, words: ['live','livestream','live stream','stream'] },
    { id: 'news',       re: /\b(news|update|patch|leak|leaks|announce|announced|release|season \d+)\b/, words: ['update','news','patch notes','leaks','new season'] },
    { id: 'promo',      re: /\b(commercial|ad|promo|launch|introducing|trailer|demo)\b/, words: ['official trailer','demo','how it works','launch','first look'] }
  ];
  var INTENT_WORDS = /\b(montage|highlights?|best moments|compilation|how to|tips?|guide|tutorial|learn|for beginners|beginners?|tricks?|explained|review|unboxing|honest|worth it|funny|fails?|memes?|moments|live|update|news|patch|leaks?|commercial|promo|trailer|demo|video|clips?)\b/g;

  /* ---------- Title templates: {C} core (Title Case), {Y} year, {N} number, {M} month, {B} brand ---------- */
  var TITLES = {
    highlights: ['{C} Highlights That Don\'t Look Real','Best {C} Moments ({Y})','This {C} Clip Is Unreal','Top {N} {C} Plays You Need to See','{C} Montage | Best Clips of {Y}','{C} Clutches Nobody Talks About'],
    howto: ['{C} Tips That Actually Work ({Y})','How to Get Better at {C} Fast','{C} for Beginners: Full Guide','{N} {C} Mistakes You\'re Still Making','The Only {C} Guide You Need in {Y}','{C} Tricks Pros Don\'t Share'],
    review: ['{C} Review: Is It Worth It in {Y}?','I Tried {C} So You Don\'t Have To','{C} Honest Review After {N} Days','{C}: The Good, the Bad, the Truth','Watch This Before You Buy {C}'],
    funny: ['{C} Funny Moments That Broke Me','Funniest {C} Moments of {Y}','{C} but Everything Goes Wrong','Try Not to Laugh: {C} Edition','{C} Fails You Have to See'],
    setup: ['Best {C} in {Y} (Meta Setup)','{C}: Settings the Pros Use','This {C} Is Broken Right Now','Best {C} You\'re Not Using','{C} Setup Guide: Copy This'],
    live: ['LIVE: {C} | Come Hang + Chill Vibes','{C} Live Grind | Playing With Viewers','{C} All Night | Road to the Top','{C} Live: Tips, Clips + Chat'],
    news: ['{C} Update: Everything You Need to Know','{C} Just Changed Everything','{C} News ({M} {Y})','Biggest {C} Changes Explained','{C} Update: Winners and Losers'],
    promo: ['{C}: See It in Action','Meet {C}: The Smarter Way to Create','{C} Official Trailer ({Y})','{C} in 60 Seconds: How It Works','Why Creators Are Switching to {C}'],
    general: ['{C}: Everything You Need to Know ({Y})','The Truth About {C}','{C} Like You\'ve Never Seen Before','Why Everyone Is Talking About {C}','Watch This Before You Try {C}','{C} Explained in Under 5 Minutes']
  };
  var DESC_TITLES = {
    video: ['{C}: The {D} That Saves Hours','Meet {C}, the {D}','{C} | {D} ({Y})','This {D} Changes Everything: {C}','{C}: {D} in Action'],
    twitch: ['{C} | {D} | Live Demo + Q&A'],
    website: ['{C}: {D}','{D} | {C}','{C}: Best {D} ({Y})']
  };
  var TWITCH_TITLES = ['{C} | Come Hang + Chill Vibes','{C} Grind | Playing With Viewers','{C} | Road to the Top | !socials','Late Night {C} | Clips + Chat','{C} Live: Tips + Chat Q&A'];
  var TWITCH_DEMO = ['{C} Live Demo | Ask Me Anything','Building With {C} Live | Q&A','{C} Live: Tips, Tricks + Chat','Testing {C} Live | Drop Your Questions'];
  var WEB_TITLES = ['{C}: Complete Guide ({Y})','{C} | {B}','Best {C} ({Y}): Tips + Tools','{C}: How It Works + Why It Matters','What Is {C}? Full Breakdown'];

  /* ---------- Helpers ---------- */
  function clean(s) { return String(s || '').toLowerCase().replace(/[^\p{L}\p{N}\s&'-]/gu, ' ').replace(/\s+/g, ' ').trim(); }
  function titleCase(s) {
    var small = /^(a|an|and|as|at|but|by|for|in|of|on|or|the|to|vs|with)$/;
    return s.split(' ').map(function (w, i) {
      if (/^\d*k\d*$/.test(w) && /\d/.test(w)) return w.toUpperCase(); // 2k27 → 2K27
      if (/^(mw\d|nba|nfl|ai|fps|gta|cod|obs|ps5|diy|ea|fc|nq|mnq|seo|saas|ui|ux|usa|tv|pc)$/.test(w)) return w.toUpperCase();
      if (w === 'takekash') return 'TakeKash';
      if (w === 'gtaxzombies') return 'GtaxZombies';
      if (i > 0 && small.test(w)) return w;
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join(' ');
  }
  function sentenceCase(s) { return titleCase(s).split(' ').map(function (w) { return /^[A-Z0-9]{2,}$/.test(w) || /^(TakeKash|GtaxZombies)$/.test(w) ? w : w.toLowerCase(); }).join(' '); }
  function hashify(s) { return '#' + String(s).toLowerCase().replace(/[^\p{L}\p{N}]/gu, ''); }
  function camel(s) { return String(s).replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/).filter(Boolean).map(function (w) { return /^[A-Z0-9]+$/.test(w) ? w : w.charAt(0).toUpperCase() + w.slice(1); }).join(''); }
  function uniq(arr) { var seen = {}, out = []; arr.forEach(function (t) { t = clean(t); if (t && t.length > 1 && !seen[t]) { seen[t] = 1; out.push(t); } }); return out; }
  function rng(seed) { var s = seed >>> 0 || 1; return function () { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 10000) / 10000; }; }
  function shuffle(arr, r) { var a = arr.slice(); for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(r() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; } return a; }
  function trimWords(s, max) { if (s.length <= max) return s; var cut = s.slice(0, max - 1); cut = cut.slice(0, cut.lastIndexOf(' ')); return cut.replace(/[,;:\-–—]+$/, '') + '…'; }
  function fill(t, ctx) { return t.replace(/\{D\}/g, ctx.D).replace(/\{C\}/g, ctx.C).replace(/\{Y\}/g, YEAR).replace(/\{N\}/g, ctx.N).replace(/\{M\}/g, MONTH).replace(/\{B\}/g, ctx.B || 'TakeKash'); }

  /* ---------- Analysis ---------- */
  function analyze(topic, catChoice, extra) {
    var t = clean(topic);
    var entities = ENTITIES.filter(function (e) { return e.re.test(t); });
    // Drop generic COD entity when a specific COD title matched
    if (entities.some(function (e) { return /warzone|modern warfare|black ops/.test(e.name); })) entities = entities.filter(function (e) { return e.name !== 'call of duty'; });
    var intents = INTENTS.filter(function (i) { return i.re.test(t); });
    var intent = intents.length ? intents[0].id : 'general';
    var cat = catChoice && catChoice !== 'auto' ? catChoice : null;
    var scores = {};
    if (!cat) {
      Object.keys(CATS).forEach(function (k) { var m = t.match(new RegExp('\\b(' + CATS[k].kw + ')', 'g')); scores[k] = m ? m.length : 0; });
      entities.forEach(function (e) { scores[e.cat] = (scores[e.cat] || 0) + 2; });
      cat = Object.keys(scores).sort(function (a, b) { return scores[b] - scores[a]; })[0];
      if (!scores[cat]) cat = 'creator';
    }
    var segs = String(topic || '').split(/\s+[-–—|:]\s+|\s*[|:–—]\s*/).map(clean).filter(Boolean);
    var t2 = segs.length ? segs.join(' ') : t;
    t = t2;
    var stripIntent = function (x) { return x.replace(INTENT_WORDS, ' ').replace(/\s+/g, ' ').trim(); };
    var core = stripIntent(segs[0] || t) || clean(segs[0] || t);
    var descriptor = segs.length > 1 ? stripIntent(segs.slice(1).join(' ')) : '';
    var words = (core + ' ' + descriptor).trim().split(' ').filter(function (w) { return STOP.indexOf(w) < 0; });
    var bigrams = []; for (var i = 0; i < words.length - 1; i++) bigrams.push(words[i] + ' ' + words[i + 1]);
    var extras = String(extra || '').split(',').map(clean).filter(Boolean);
    return { topic: t, core: core, descriptor: descriptor, words: words, bigrams: bigrams, entities: entities, intent: intent, intents: intents, cat: cat, catData: CATS[cat], extras: extras };
  }

  /* ---------- Tags (4 tiers) ---------- */
  function dedupeWords(x) { var seen = {}; return x.split(' ').filter(function (w) { if (seen[w] && STOP.indexOf(w) < 0 || (seen[w] && w === 'best')) return false; seen[w] = 1; return true; }).join(' '); }
  function okTag(x) { return x && x.split(' ').length <= 6 && x.length <= 60; }
  function okSingle(w, a) { return w.length >= 5 || /\d/.test(w) || a.entities.some(function (e) { return e.name === w; }); }
  function buildTags(a) {
    var core = a.core, intentWords = [];
    a.intents.forEach(function (i) { intentWords = intentWords.concat(i.words); });
    if (!intentWords.length) intentWords = ['tips','explained','guide'];
    intentWords = intentWords.filter(function (w) { return w !== 'how to'; });
    var hasBest = /\bbest\b/.test(core);
    var contentEnts = a.entities.filter(function (e) { return !e.meta; });

    var metaHit = a.entities.some(function (e) { return e.meta; });
    var tierCore = uniq([metaHit ? (core + ' ' + a.descriptor).trim() : a.topic, core, a.descriptor].concat(a.extras, contentEnts.map(function (e) { return e.name; }), a.bigrams,
      a.words.filter(function (w) { return okSingle(w, a); }))).filter(function (x) { return !(metaHit && /\b(commercial|promo|advert)\b/.test(x)); }).filter(okTag);

    var similar = [];
    contentEnts.forEach(function (e) { similar = similar.concat(e.rel); });
    intentWords.forEach(function (w) { similar.push(core + ' ' + w); });
    if (a.descriptor) similar.push(core + ' ' + a.descriptor.split(' ').slice(0, 2).join(' '));
    contentEnts.forEach(function (e) { if (e.name !== core) intentWords.slice(0, 2).forEach(function (w) { similar.push(e.name + ' ' + w); }); });
    var tierSimilar = uniq(similar.map(dedupeWords)).filter(okTag).filter(function (x) { return tierCore.indexOf(x) < 0; });

    var lt = [(hasBest ? '' : 'best ') + core + ' ' + YEAR, core + ' ' + YEAR, core + ' for beginners', core + ' tips and tricks', core + ' explained'];
    if (/how to/.test(a.topic)) lt.push('how to ' + core);
    if (a.intent === 'highlights' || a.intent === 'howto') lt.push('how to get better at ' + core);
    if (a.intent === 'review' || a.intent === 'promo') lt.push('is ' + core + ' worth it', core + ' review', core + ' alternative');
    if (a.descriptor) lt.push('best ' + a.descriptor, a.descriptor + ' ' + YEAR);
    var tierLong = uniq(lt.map(dedupeWords)).filter(okTag).filter(function (x) { return tierCore.indexOf(x) < 0 && tierSimilar.indexOf(x) < 0; });

    var tierBroad = uniq(a.catData.broad.slice());
    a.entities.forEach(function (e) { if (e.cat !== a.cat) tierBroad = uniq(tierBroad.concat(CATS[e.cat].broad.slice(0, 3))); });

    return { core: tierCore, similar: tierSimilar, longtail: tierLong, broad: tierBroad };
  }

  /* YouTube packs tags until 500 chars. Multi-word tags count +2 (implied quotes), commas count. */
  function packYouTubeTags(tags, budget) {
    var out = [], used = 0;
    for (var i = 0; i < tags.length; i++) {
      var t = tags[i]; if (t.length > 100) continue;
      var cost = t.length + (t.indexOf(' ') >= 0 ? 2 : 0) + (out.length ? 1 : 0);
      if (used + cost > budget) continue;
      out.push(t); used += cost;
    }
    return { tags: out, used: used };
  }
  function interleave(tiers) { // core first, then round-robin longtail/similar/broad
    var out = tiers.core.slice(0, 6), lists = [tiers.longtail, tiers.similar, tiers.broad, tiers.core.slice(6)], i = 0, added = true;
    while (added) { added = false; lists.forEach(function (l) { if (l[i]) { out.push(l[i]); added = true; } }); i++; }
    return uniq(out);
  }
  function pickHashtags(tiers, n, plat, a) {
    var pool = [];
    if (plat === 'shorts') pool.push('shorts');
    a.entities.filter(function (e) { return !e.meta; }).forEach(function (e) { pool.push(e.name); });
    if (a.core.split(' ').length <= 2) pool.push(a.core);
    tiers.core.filter(function (x) { return x.split(' ').length <= 2; }).slice(0, 3).forEach(function (x) { pool.push(x); });
    tiers.similar.filter(function (x) { return x.split(' ').length <= 2; }).slice(0, 3).forEach(function (x) { pool.push(x); });
    pool.push(tiers.broad[0]);
    var seen = {}, out = [];
    pool.filter(Boolean).map(hashify).forEach(function (h) { if (h.length > 2 && h.length <= 22 && !seen[h]) { seen[h] = 1; out.push(h); } });
    // reserve the last slot for the broad category tag (maximum audience)
    var broad = hashify(tiers.broad[0]);
    out = out.filter(function (h) { return h !== broad; }).slice(0, n - 1).concat([broad]);
    var extra = tiers.broad.slice(1).map(hashify);
    for (var i = 0; out.length < n && i < extra.length; i++) if (out.indexOf(extra[i]) < 0) out.push(extra[i]);
    return out.slice(0, n);
  }
  function twitchTags(a, tiers, lang) {
    var cands = [];
    a.entities.forEach(function (e) { cands = cands.concat(e.twitch); });
    cands = cands.concat(tiers.core.filter(function (x) { return x.split(' ').length <= 3; }).slice(0, 2).map(camel), a.catData.twitch, [lang || 'English']);
    cands = cands.concat(tiers.similar.slice(0, 6).map(camel), tiers.broad.slice(0, 4).map(camel));
    var seen = {}, out = [];
    cands.forEach(function (c) { c = String(c).replace(/[^\p{L}\p{N}]/gu, ''); var k = c.toLowerCase(); if (c && c.length <= 25 && !seen[k]) { seen[k] = 1; out.push(c); } });
    return out.slice(0, 10);
  }

  /* ---------- Titles ---------- */
  function buildTitles(a, platKey, opts, r) {
    var P = PLATFORMS[platKey];
    var ctx = { C: titleCase(a.core), D: titleCase(a.descriptor || ''), N: [3, 5, 7, 10][Math.floor(r() * 4)], B: opts.brand };
    var bank = platKey === 'twitch' ? (a.cat === 'gaming' ? TWITCH_TITLES : TWITCH_DEMO) : platKey === 'website' ? WEB_TITLES.filter(function (x) { return a.intent !== 'promo' || !/^Best \{C\}/.test(x); }) : (TITLES[a.intent] || TITLES.general).concat(TITLES.general.slice(0, 2));
    if (a.descriptor) bank = DESC_TITLES[platKey === 'website' ? 'website' : platKey === 'twitch' ? 'twitch' : 'video'].concat(bank);
    var titles = shuffle(bank, r).map(function (tpl) { return fill(tpl, ctx); });
    if (platKey === 'website' && opts.brand) titles = titles.map(function (t) { return t.indexOf(opts.brand) >= 0 || t.length + opts.brand.length + 3 > P.titleMax ? t : t + ' | ' + opts.brand; });
    if (platKey === 'shorts') titles = titles.map(function (t) { return t.replace(/\s*\(\d{4}\)/, ''); });
    if (platKey === 'tiktok' || platKey === 'instagram') titles = titles.map(function (t) { return t.replace(/\s*\(\d{4}\)/, ''); });
    titles = titles.filter(function (t) { return t.length <= P.titleMax && !/^(.+) \| \1$/.test(t); });
    var kw = a.core.split(' ')[0];
    return uniq(titles).map(function (t, i) { return titles.filter(function (x) { return clean(x) === t; })[0]; })
      .map(function (t) {
        var pos = clean(t).indexOf(kw), score = 100;
        if (pos > 20) score -= 15; if (t.length > P.titleVisible) score -= 20; if (t.length < 25 && platKey !== 'shorts') score -= 10;
        return { text: t, len: t.length, visible: P.titleVisible, max: P.titleMax, fits: t.length <= P.titleVisible, score: score };
      }).sort(function (x, y) { return y.score - x.score; }).slice(0, 6);
  }

  /* ---------- Descriptions ---------- */
  function buildDescription(a, platKey, tiers, hashtags, opts) {
    var C = titleCase(a.core), D = a.descriptor ? titleCase(a.descriptor) : '', cd = a.catData, brand = opts.brand || '', topTags = tiers.similar.slice(0, 3);
    var aud = cd.audience;
    var hook = {
      highlights: C + ' highlights packed with the best plays, clutches and moments ' + aud + ' love.',
      howto: 'Learn ' + C + ' the fast way: practical tips that work in ' + YEAR + ', even if you are just starting.',
      review: 'An honest ' + C + ' review: what works, what does not, and whether it is worth it in ' + YEAR + '.',
      funny: 'The funniest ' + C + ' moments, fails and reactions in one place.',
      setup: 'The best ' + C + ' setup for ' + YEAR + ', with the exact settings so you can copy it.',
      live: C + ' live: chill vibes, real gameplay and chat hangouts.',
      news: 'Everything new in ' + C + ' this ' + MONTH + ', explained fast so you are caught up.',
      promo: D ? C + ' is the ' + sentenceCase(a.descriptor) + ' built to save you hours. Here is how it works and why it matters.' : 'Meet ' + C + ': see how it works, who it is for, and why it matters.',
      general: 'Everything you need to know about ' + C + ' in ' + YEAR + ', explained simply.'
    }[a.intent];
    var context = 'Covers ' + [a.core].concat(topTags).slice(0, 4).map(sentenceCase).join(', ') + ' and more for ' + aud + '.';
    var follow = cd.cta.replace(/subscribe/i, function (m) { return m[0] === 'S' ? 'Follow' : 'follow'; });

    if (platKey === 'youtube') {
      return [hook, context, '',
        '⏱️ Chapters (edit times; first must be 0:00, 3+ chapters, 10s+ each)', '0:00 Intro', '0:15 ' + C, '0:45 [next section]', '',
        '👉 ' + cd.cta,
        brand ? '🔗 ' + brand + ': [your link]' : '🔗 [your link]', '',
        hashtags.join(' ')].join('\n');
    }
    if (platKey === 'shorts') return [hook, cd.cta, '', hashtags.join(' ')].join('\n');
    if (platKey === 'tiktok') return [hook + ' ' + follow, '', hashtags.join(' ')].join('\n');
    if (platKey === 'instagram') return [hook, '', follow + (brand ? ' Link in bio @' + brand.replace(/\s/g, '').toLowerCase() + '.' : ''), '', hashtags.join(' ')].join('\n');
    if (platKey === 'twitch') return trimWords(C + ' streams for ' + aud + ': ' + (a.cat === 'gaming' ? 'gameplay, tips, and good vibes' : 'live demos, tips, and Q&A') + '. Follow to get notified when we go live' + (brand ? ' — ' + brand : '') + '.', 300);
    if (platKey === 'website') {
      // build from whole sentences so it never ends mid-thought; target 140-158 chars
      var parts = [hook, follow, context], meta = '';
      parts.forEach(function (p) { if ((meta + ' ' + p).trim().length <= 158) meta = (meta + ' ' + p).trim(); });
      if (!meta) meta = trimWords(hook, 157).replace(/…$/, '.');
      return meta;
    }
    return hook;
  }

  /* ---------- Public API ---------- */
  function generate(input) {
    var opts = { brand: (input.brand || '').trim(), lang: input.lang || 'English' };
    var a = analyze(input.topic, input.category, input.extra);
    var tiers = buildTags(a);
    var r = rng((input.seed || 7) * 2654435761 + a.topic.length);
    var plats = input.platform === 'all' ? Object.keys(PLATFORMS) : [input.platform];
    var results = {};
    plats.forEach(function (p) {
      var P = PLATFORMS[p], res = { platform: p, label: P.label };
      res.titles = buildTitles(a, p, opts, r);
      if (p === 'youtube' || p === 'shorts') {
        res.hashtags = pickHashtags(tiers, P.hashtags, p, a);
        var packed = packYouTubeTags(interleave(tiers), P.tagBudget);
        res.tags = packed.tags; res.tagChars = packed.used; res.tagBudget = P.tagBudget;
      } else if (p === 'tiktok' || p === 'instagram') {
        res.hashtags = pickHashtags(tiers, P.hashtags, p, a);
      } else if (p === 'twitch') {
        res.twitchTags = twitchTags(a, tiers, opts.lang);
      } else if (p === 'website') {
        res.slug = '/' + a.core.split(' ').filter(function (w) { return STOP.indexOf(w) < 0; }).join('-').replace(/[^a-z0-9-]/g, '').replace(/-+/g, '-');
        res.keywords = { focus: a.core, secondary: tiers.longtail.slice(0, 3).concat(tiers.similar.slice(0, 3)) };
        res.h1 = titleCase(a.core) + ': ' + ({ howto: 'The Complete Guide', review: 'Honest Review', promo: 'How It Works' }[a.intent] || 'Everything You Need to Know');
      }
      res.description = buildDescription(a, p, tiers, res.hashtags || [], opts);
      res.descLen = res.description.length; res.descMax = P.descMax;
      results[p] = res;
    });
    return { analysis: { core: a.core, category: a.cat, categoryLabel: a.catData.label, intent: a.intent, entities: a.entities.map(function (e) { return e.name; }) }, tiers: tiers, results: results };
  }

  var api = { generate: generate, PLATFORMS: PLATFORMS, CATS: CATS, hashify: hashify, camel: camel, packYouTubeTags: packYouTubeTags };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.TKSEO = api;
})(this);

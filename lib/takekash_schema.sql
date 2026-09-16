-- TakeKash real database schema, per the SEO automation + Direct
-- Post architecture spec. SQLite: a real, local, genuine database -
-- no cloud account needed to start using this, unlike the queue's
-- current flat publish_schedule.json file.

CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_video TEXT NOT NULL,
    clip_path TEXT NOT NULL,
    duration REAL,
    game TEXT,
    character TEXT,
    mode TEXT,
    rank TEXT,
    hook TEXT,
    seo_score INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS social_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    username TEXT,
    access_token TEXT,
    refresh_token TEXT,
    expires_at REAL,
    open_id TEXT,
    status TEXT NOT NULL DEFAULT 'disconnected',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS social_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER NOT NULL REFERENCES clips(id),
    platform TEXT NOT NULL,
    title TEXT,
    description TEXT,
    hashtags TEXT,
    keywords TEXT,
    publish_id TEXT,
    platform_post_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_for TEXT,
    published_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_social_posts_clip_id ON social_posts(clip_id);
CREATE INDEX IF NOT EXISTS idx_social_posts_status ON social_posts(status);
CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);

CREATE TABLE IF NOT EXISTS analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    social_post_id INTEGER NOT NULL REFERENCES social_posts(id),
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    watch_time_sec REAL,
    completion_rate REAL,
    followers_gained INTEGER DEFAULT 0,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_analytics_post_id ON analytics(social_post_id);

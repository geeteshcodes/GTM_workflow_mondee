-- voice_agent/db_schema.sql
-- ----------------------------------------------------------------------------
-- Run this once against gtm_uae to create the outreach call tables.
-- Mirrors the original SQLite schema from the standalone voice agent,
-- but in PostgreSQL and linked to the partners table.
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS outreach_calls (
    id           SERIAL PRIMARY KEY,
    call_sid     TEXT UNIQUE NOT NULL,
    partner_id   INTEGER REFERENCES partners(id),
    partner_name TEXT,
    mission      TEXT,
    to_number    TEXT,
    from_number  TEXT,
    status       TEXT DEFAULT 'initiated',
    duration_s   INTEGER DEFAULT 0,
    started_at   TIMESTAMP,
    ended_at     TIMESTAMP,
    created_at   TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS outreach_transcript_lines (
    id         SERIAL PRIMARY KEY,
    call_sid   TEXT NOT NULL REFERENCES outreach_calls(call_sid),
    speaker    TEXT,
    line_text  TEXT,
    spoken_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outreach_call_summaries (
    id              SERIAL PRIMARY KEY,
    call_sid        TEXT UNIQUE NOT NULL REFERENCES outreach_calls(call_sid),
    outcome         TEXT,
    key_points      JSONB,
    action_items    JSONB,
    sentiment       TEXT,
    notable_quotes  JSONB,
    raw_summary     TEXT,
    created_at      TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_outreach_calls_partner_id ON outreach_calls (partner_id);
CREATE INDEX IF NOT EXISTS idx_outreach_calls_status ON outreach_calls (status);
CREATE INDEX IF NOT EXISTS idx_outreach_transcript_call_sid ON outreach_transcript_lines (call_sid);
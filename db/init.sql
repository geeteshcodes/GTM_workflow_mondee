-- partners table
CREATE TABLE IF NOT EXISTS partners (
    id               SERIAL PRIMARY KEY,
    partner_name     TEXT,
    digitisation     TEXT,
    category         TEXT,
    subcategories    TEXT,
    website          TEXT,
    product_count    INTEGER,
    status           TEXT,
    integrated       TEXT,
    region           TEXT,
    phone_number     TEXT,
    email_id         TEXT,
    linkedin_profile TEXT,
    sheet_source     TEXT
);

CREATE INDEX IF NOT EXISTS idx_partners_status
    ON partners (status);

CREATE INDEX IF NOT EXISTS idx_partners_subcategories_gin
    ON partners USING gin (to_tsvector('english', COALESCE(subcategories, '')));

CREATE INDEX IF NOT EXISTS idx_partners_name
    ON partners (partner_name);
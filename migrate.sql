-- Migration: Company to Asset terminology
ALTER TABLE companies RENAME TO assets;
ALTER TABLE social_posts RENAME COLUMN company_id TO asset_id;
ALTER TABLE alerts RENAME COLUMN company_id TO asset_id;
ALTER TABLE notification_preferences RENAME COLUMN company_id TO asset_id;

ALTER TABLE social_posts
DROP CONSTRAINT social_posts_company_id_fkey,
ADD CONSTRAINT social_posts_asset_id_fkey
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE;

ALTER TABLE alerts
DROP CONSTRAINT alerts_company_id_fkey,
ADD CONSTRAINT alerts_asset_id_fkey
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE;

ALTER TABLE notification_preferences
DROP CONSTRAINT notification_preferences_company_id_fkey,
ADD CONSTRAINT notification_preferences_asset_id_fkey
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE;

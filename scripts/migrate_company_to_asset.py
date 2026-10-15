"""
Migrate Company to Asset terminology
Renames companies table and all related columns to support broader financial instruments.
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(DATABASE_URL)


def migrate_company_to_asset():
    """Migrate database schema from companies to assets terminology."""
    conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            logger.info("Starting migration from Company to Asset terminology...")

            # Step 1: Rename companies table to assets
            logger.info("Step 1: Renaming companies table to assets...")
            cur.execute("""
                ALTER TABLE companies RENAME TO assets;
            """)
            logger.info("✓ Table renamed: companies → assets")

            # Step 2: Rename company_id column in social_posts table
            logger.info("Step 2: Renaming company_id in social_posts...")
            cur.execute("""
                ALTER TABLE social_posts RENAME COLUMN company_id TO asset_id;
            """)
            logger.info("✓ Column renamed: social_posts.company_id → asset_id")

            # Step 3: Rename company_id column in alerts table
            logger.info("Step 3: Renaming company_id in alerts...")
            cur.execute("""
                ALTER TABLE alerts RENAME COLUMN company_id TO asset_id;
            """)
            logger.info("✓ Column renamed: alerts.company_id → asset_id")

            # Step 4: Rename company_id column in notification_preferences table
            logger.info("Step 4: Renaming company_id in notification_preferences...")
            cur.execute("""
                ALTER TABLE notification_preferences RENAME COLUMN company_id TO asset_id;
            """)
            logger.info("✓ Column renamed: notification_preferences.company_id → asset_id")

            # Step 5: Rename foreign key constraints (for clarity, though not strictly necessary)
            logger.info("Step 5: Renaming foreign key constraints...")

            # Social posts FK
            cur.execute("""
                ALTER TABLE social_posts
                DROP CONSTRAINT social_posts_company_id_fkey,
                ADD CONSTRAINT social_posts_asset_id_fkey
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE;
            """)
            logger.info("✓ FK renamed: social_posts_company_id_fkey → social_posts_asset_id_fkey")

            # Alerts FK
            cur.execute("""
                ALTER TABLE alerts
                DROP CONSTRAINT alerts_company_id_fkey,
                ADD CONSTRAINT alerts_asset_id_fkey
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE;
            """)
            logger.info("✓ FK renamed: alerts_company_id_fkey → alerts_asset_id_fkey")

            # Notification preferences FK
            cur.execute("""
                ALTER TABLE notification_preferences
                DROP CONSTRAINT notification_preferences_company_id_fkey,
                ADD CONSTRAINT notification_preferences_asset_id_fkey
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE;
            """)
            logger.info("✓ FK renamed: notification_preferences_company_id_fkey → notification_preferences_asset_id_fkey")

            # Commit all changes
            conn.commit()
            logger.info("\n✅ Migration completed successfully!")
            logger.info("Database schema updated: Company → Asset")

            # Verify the changes
            logger.info("\nVerifying migration...")
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'assets';
            """)
            if cur.fetchone():
                logger.info("✓ 'assets' table exists")

            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'social_posts' AND column_name = 'asset_id';
            """)
            if cur.fetchone():
                logger.info("✓ social_posts.asset_id column exists")

            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'alerts' AND column_name = 'asset_id';
            """)
            if cur.fetchone():
                logger.info("✓ alerts.asset_id column exists")

            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'notification_preferences' AND column_name = 'asset_id';
            """)
            if cur.fetchone():
                logger.info("✓ notification_preferences.asset_id column exists")

    except Exception as e:
        conn.rollback()
        logger.error(f"Error during migration: {e}")
        logger.error("Rolling back changes...")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    logger.info("="*60)
    logger.info("Database Migration: Company → Asset")
    logger.info("="*60)

    try:
        migrate_company_to_asset()
        logger.info("\n🎉 Migration successful! The database now uses 'Asset' terminology.")
        logger.info("Next steps: Update application code to use new table/column names.")
    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}")
        sys.exit(1)

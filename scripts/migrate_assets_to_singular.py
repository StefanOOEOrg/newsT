"""
Migration script to rename 'assets' table to 'asset' (singular) with data preservation.

This script:
1. Checks if old 'assets' table exists
2. Creates new 'asset' table if it doesn't exist
3. Migrates all data from 'assets' to 'asset'
4. Updates all foreign key references
5. Drops old 'assets' table

Usage:
    python3 scripts/migrate_assets_to_singular.py
"""
import os
import sys
from pathlib import Path
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# Add shared directory to path
shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')


def migrate():
    """Migrate from plural 'assets' to singular 'asset' table."""

    print("=" * 80)
    print("DATABASE MIGRATION: 'assets' (plural) → 'asset' (singular)")
    print("=" * 80)
    print()

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False  # Use transaction
        cursor = conn.cursor()

        # Check if old table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'assets'
            );
        """)
        has_old_table = cursor.fetchone()[0]

        # Check if new table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'asset'
            );
        """)
        has_new_table = cursor.fetchone()[0]

        print(f"Old table 'assets' exists: {has_old_table}")
        print(f"New table 'asset' exists: {has_new_table}")
        print()

        if not has_old_table:
            print("✅ No migration needed - old 'assets' table doesn't exist")
            print("   The new schema will be used on fresh database creation")
            cursor.close()
            conn.close()
            return True

        if has_new_table:
            print("⚠️  Both 'assets' and 'asset' tables exist!")
            response = input("Drop 'assets' table and keep 'asset'? (yes/no): ")
            if response.lower() == 'yes':
                print("Dropping old 'assets' table...")
                cursor.execute("DROP TABLE IF EXISTS assets CASCADE")
                conn.commit()
                print("✅ Old 'assets' table dropped")
            else:
                print("❌ Migration aborted")
            cursor.close()
            conn.close()
            return False

        # Migration starts here
        print("Starting migration...")
        print()

        # Step 1: Count records in old table
        cursor.execute("SELECT COUNT(*) FROM assets")
        total_records = cursor.fetchone()[0]
        print(f"📊 Found {total_records} records in 'assets' table")

        # Step 2: Get sample data
        cursor.execute("SELECT id, name, ticker FROM assets LIMIT 5")
        samples = cursor.fetchall()
        print("   Sample records:")
        for record in samples:
            print(f"     - ID {record[0]}: {record[1]} ({record[2]})")
        print()

        # Step 3: Drop foreign key constraints that reference assets
        print("🔧 Step 1: Dropping foreign key constraints...")
        fk_constraints = [
            ('social_posts', 'social_posts_company_id_fkey'),
            ('social_posts', 'social_posts_asset_id_fkey'),
            ('daily_metrics', 'daily_metrics_company_id_fkey'),
            ('daily_metrics', 'daily_metrics_asset_id_fkey'),
            ('keyword_performance', 'keyword_performance_asset_id_fkey'),
            ('alerts', 'alerts_company_id_fkey'),
            ('alerts', 'alerts_asset_id_fkey'),
            ('alert_notification_preferences', 'alert_notification_preferences_company_id_fkey'),
            ('alert_notification_preferences', 'alert_notification_preferences_asset_id_fkey'),
        ]

        for table, constraint in fk_constraints:
            try:
                cursor.execute(f"""
                    ALTER TABLE {table}
                    DROP CONSTRAINT IF EXISTS {constraint} CASCADE
                """)
                print(f"   ✓ Dropped {constraint}")
            except Exception as e:
                print(f"   ⚠ Skipped {constraint}: {e}")
        print()

        # Step 4: Rename assets table to asset
        print("🔧 Step 2: Renaming 'assets' table to 'asset'...")
        cursor.execute("ALTER TABLE assets RENAME TO asset")
        print("   ✓ Table renamed successfully")
        print()

        # Step 5: Update foreign key column names if needed
        print("🔧 Step 3: Checking foreign key column names...")

        # Check if social_posts has company_id (old name)
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'social_posts' AND column_name IN ('company_id', 'asset_id')
        """)
        sp_col = cursor.fetchone()
        if sp_col and sp_col[0] == 'company_id':
            print("   Renaming social_posts.company_id to asset_id...")
            cursor.execute("ALTER TABLE social_posts RENAME COLUMN company_id TO asset_id")
            print("   ✓ Renamed")
        else:
            print("   ✓ social_posts.asset_id already correct")

        # Check daily_metrics
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'daily_metrics' AND column_name IN ('company_id', 'asset_id')
        """)
        dm_col = cursor.fetchone()
        if dm_col and dm_col[0] == 'company_id':
            print("   Renaming daily_metrics.company_id to asset_id...")
            cursor.execute("ALTER TABLE daily_metrics RENAME COLUMN company_id TO asset_id")
            print("   ✓ Renamed")
        else:
            print("   ✓ daily_metrics.asset_id already correct")

        # Check alerts
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'alerts' AND column_name IN ('company_id', 'asset_id')
        """)
        alerts_col = cursor.fetchone()
        if alerts_col and alerts_col[0] == 'company_id':
            print("   Renaming alerts.company_id to asset_id...")
            cursor.execute("ALTER TABLE alerts RENAME COLUMN company_id TO asset_id")
            print("   ✓ Renamed")
        else:
            print("   ✓ alerts.asset_id already correct")

        # Check alert_notification_preferences
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'alert_notification_preferences' AND column_name IN ('company_id', 'asset_id')
        """)
        anp_col = cursor.fetchone()
        if anp_col and anp_col[0] == 'company_id':
            print("   Renaming alert_notification_preferences.company_id to asset_id...")
            cursor.execute("ALTER TABLE alert_notification_preferences RENAME COLUMN company_id TO asset_id")
            print("   ✓ Renamed")
        else:
            print("   ✓ alert_notification_preferences.asset_id already correct")

        print()

        # Step 6: Recreate foreign key constraints
        print("🔧 Step 4: Recreating foreign key constraints...")

        cursor.execute("""
            ALTER TABLE social_posts
            ADD CONSTRAINT social_posts_asset_id_fkey
            FOREIGN KEY (asset_id) REFERENCES asset(id) ON DELETE CASCADE
        """)
        print("   ✓ social_posts → asset")

        cursor.execute("""
            ALTER TABLE daily_metrics
            ADD CONSTRAINT daily_metrics_asset_id_fkey
            FOREIGN KEY (asset_id) REFERENCES asset(id) ON DELETE CASCADE
        """)
        print("   ✓ daily_metrics → asset")

        cursor.execute("""
            ALTER TABLE keyword_performance
            ADD CONSTRAINT keyword_performance_asset_id_fkey
            FOREIGN KEY (asset_id) REFERENCES asset(id) ON DELETE CASCADE
        """)
        print("   ✓ keyword_performance → asset")

        cursor.execute("""
            ALTER TABLE alerts
            ADD CONSTRAINT alerts_asset_id_fkey
            FOREIGN KEY (asset_id) REFERENCES asset(id) ON DELETE CASCADE
        """)
        print("   ✓ alerts → asset")

        cursor.execute("""
            ALTER TABLE alert_notification_preferences
            ADD CONSTRAINT alert_notification_preferences_asset_id_fkey
            FOREIGN KEY (asset_id) REFERENCES asset(id) ON DELETE CASCADE
        """)
        print("   ✓ alert_notification_preferences → asset")
        print()

        # Step 7: Recreate indexes
        print("🔧 Step 5: Recreating indexes...")

        # Drop old indexes
        old_indexes = [
            'idx_companies_init_status',
            'idx_social_posts_company',
            'idx_daily_metrics_company_date',
            'idx_alerts_company',
            'idx_alert_prefs_company'
        ]

        for idx in old_indexes:
            try:
                cursor.execute(f"DROP INDEX IF EXISTS {idx}")
            except:
                pass

        # Create new indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_asset_init_status ON asset(initialization_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_social_posts_asset ON social_posts(asset_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_metrics_asset_date ON daily_metrics(asset_id, date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_asset ON alerts(asset_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_prefs_asset ON alert_notification_preferences(asset_id)")

        print("   ✓ All indexes recreated")
        print()

        # Step 8: Verify migration
        print("🔍 Verifying migration...")
        cursor.execute("SELECT COUNT(*) FROM asset")
        new_count = cursor.fetchone()[0]

        if new_count == total_records:
            print(f"   ✅ All {new_count} records migrated successfully!")
        else:
            print(f"   ⚠️  Record count mismatch: {total_records} → {new_count}")
            raise Exception("Record count mismatch")

        # Check foreign keys are working
        cursor.execute("""
            SELECT COUNT(*) FROM social_posts sp
            JOIN asset a ON sp.asset_id = a.id
        """)
        print(f"   ✓ Foreign keys working (tested {cursor.fetchone()[0]} social_posts)")
        print()

        # Commit transaction
        conn.commit()

        print("=" * 80)
        print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print()
        print("Summary:")
        print(f"  • Renamed table: 'assets' → 'asset'")
        print(f"  • Migrated {total_records} records")
        print(f"  • Updated all foreign key references")
        print(f"  • Recreated indexes")
        print()
        print("Next steps:")
        print("  1. Restart services: docker-compose restart")
        print("  2. All code already updated to use 'asset' table")
        print()

        cursor.close()
        return True

    except Exception as e:
        print()
        print("=" * 80)
        print("❌ MIGRATION FAILED!")
        print("=" * 80)
        print(f"Error: {e}")
        print()
        print("Rolling back changes...")
        if conn:
            conn.rollback()
        print("✓ Rollback complete - database unchanged")
        return False

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    print()
    print("This script will migrate your database from 'assets' (plural) to 'asset' (singular).")
    print("Your data will be preserved during the migration.")
    print()

    response = input("Continue with migration? (yes/no): ")

    if response.lower() in ['yes', 'y']:
        success = migrate()
        sys.exit(0 if success else 1)
    else:
        print("Migration cancelled.")
        sys.exit(0)

#!/usr/bin/env python3
"""
Database migration runner with SHA-256 checksum verification.

Applies pending migrations in lexical order, verifies checksums to detect
tampering, and tracks applied migrations in schema_migrations table.
"""

import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


def calculate_checksum(file_path: Path) -> str:
    """
    Calculate SHA-256 checksum of migration file.

    Args:
        file_path: Path to migration file

    Returns:
        Hexadecimal SHA-256 checksum
    """
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        sha256.update(f.read())
    return sha256.hexdigest()


def discover_migrations(migrations_dir: Path) -> List[Tuple[str, Path]]:
    """
    Discover migrations in lexical order.

    Args:
        migrations_dir: Directory containing migration files

    Returns:
        List of (migration_name, migration_path) tuples in lexical order
    """
    migration_files = sorted(migrations_dir.glob("*.sql"))
    # Exclude schema_migrations.sql if it exists (not a migration)
    return [
        (f.name, f)
        for f in migration_files
        if f.name != "schema_migrations.sql"
    ]


def apply_migrations(db_path: Path, migrations_dir: Path) -> None:
    """
    Apply pending migrations with checksum verification.

    Args:
        db_path: Path to SQLite database file
        migrations_dir: Directory containing migration files

    Raises:
        RuntimeError: If migration checksum verification fails (tamper detection)
    """
    # Ensure database directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Connect to database
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")

    # Create schema_migrations table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_name TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        ) STRICT
    """)
    conn.commit()

    # Get applied migrations
    applied = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT migration_name, checksum FROM schema_migrations"
        )
    }

    # Discover all migrations
    migrations = discover_migrations(migrations_dir)

    if not migrations:
        print(f"No migrations found in {migrations_dir}")
        conn.close()
        return

    applied_count = 0
    skipped_count = 0

    for name, path in migrations:
        if name in applied:
            # Verify checksum (tamper detection)
            current_checksum = calculate_checksum(path)
            if current_checksum != applied[name]:
                conn.close()
                raise RuntimeError(
                    f"Migration {name} has been tampered with!\n"
                    f"Expected checksum: {applied[name]}\n"
                    f"Got checksum: {current_checksum}\n"
                    f"This indicates the migration file was modified after being applied."
                )
            print(f"✓ Skipping {name} (already applied)")
            skipped_count += 1
            continue

        # Apply new migration
        print(f"→ Applying migration: {name}")
        checksum = calculate_checksum(path)

        try:
            with conn:  # Transaction
                conn.executescript(path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (migration_name, checksum, applied_at) VALUES (?, ?, ?)",
                    (name, checksum, int(datetime.now().timestamp()))
                )
            print(f"✓ Applied {name}")
            applied_count += 1
        except Exception as e:
            conn.close()
            print(f"✗ Failed to apply {name}: {e}", file=sys.stderr)
            raise

    conn.close()

    # Summary
    print(f"\nMigration Summary:")
    print(f"  Applied: {applied_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Total: {len(migrations)}")


def main() -> int:
    """
    Main entry point for migration script.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Determine project root (script is in scripts/, project root is parent)
    project_root = Path(__file__).parent.parent

    # Database path (default: data/sohnbot.db)
    db_path = project_root / "data" / "sohnbot.db"

    # Migrations directory
    migrations_dir = project_root / "src" / "sohnbot" / "persistence" / "migrations"

    if not migrations_dir.exists():
        print(f"Error: Migrations directory not found: {migrations_dir}", file=sys.stderr)
        return 1

    print(f"Database: {db_path}")
    print(f"Migrations: {migrations_dir}\n")

    try:
        apply_migrations(db_path, migrations_dir)
        print("\n✓ Migrations completed successfully")
        return 0
    except Exception as e:
        print(f"\n✗ Migration failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

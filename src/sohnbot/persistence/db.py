"""Database connection management with WAL mode and pragma configuration."""

import aiosqlite
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Manages SQLite database connections with WAL mode and optimal pragmas."""

    def __init__(self, db_path: str | Path):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._connection: Optional[aiosqlite.Connection] = None

    async def get_connection(self) -> aiosqlite.Connection:
        """
        Get database connection with WAL mode and optimized pragmas.

        Returns:
            SQLite connection with WAL mode enabled

        Note:
            Connection is cached after first creation for connection pooling.
            All pragmas are set on connection creation.
        """
        if self._connection is not None:
            return self._connection

        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create connection
        conn = await aiosqlite.connect(str(self.db_path))

        try:
            # Configure pragmas for optimal performance and safety
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("PRAGMA temp_store=MEMORY")
            await conn.execute("PRAGMA cache_size=-64000")

            # Verify WAL mode was enabled
            cursor = await conn.execute("PRAGMA journal_mode")
            mode = await cursor.fetchone()
            await cursor.close()

            if mode[0].lower() != 'wal':
                await conn.close()
                raise RuntimeError(
                    f"Failed to enable WAL mode. Expected 'wal', got '{mode[0]}'. "
                    "WAL mode is required for safe concurrent access."
                )
        except Exception:
            # Clean up connection on any pragma configuration failure
            await conn.close()
            raise

        logger.info(
            "database_connection_established",
            db_path=str(self.db_path),
            journal_mode=mode[0]
        )

        # Cache connection for reuse
        self._connection = conn
        return conn

    async def init_db(self) -> None:
        """
        Initialize database by creating schema_migrations table.

        Note: Does NOT apply migrations. Use migrate.py script for that.
        """
        conn = await self.get_connection()

        # Apply migrations (simple approach for now)
        migrations_dir = Path(__file__).parent / "migrations"
        if migrations_dir.exists():
            # Create schema_migrations table first
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_name TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at INTEGER NOT NULL
                ) STRICT
            """)
            await conn.commit()

            logger.info(
                "database_initialized",
                db_path=str(self.db_path),
                migrations_dir=str(migrations_dir)
            )

    async def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.info("database_connection_closed", db_path=str(self.db_path))


# Global database manager instance (initialized by main application)
_db_manager: Optional[DatabaseManager] = None


def set_db_manager(manager: DatabaseManager) -> None:
    """
    Set global database manager instance.

    Args:
        manager: DatabaseManager instance to use globally
    """
    global _db_manager
    _db_manager = manager


def get_db_manager() -> DatabaseManager:
    """
    Get global database manager instance.

    Returns:
        Global DatabaseManager instance

    Raises:
        RuntimeError: If database manager not initialized
    """
    if _db_manager is None:
        raise RuntimeError(
            "Database manager not initialized. Call set_db_manager() first."
        )
    return _db_manager


async def get_db() -> aiosqlite.Connection:
    """
    Get database connection from global manager.

    Returns:
        SQLite connection with WAL mode enabled

    Raises:
        RuntimeError: If database manager not initialized
    """
    return await get_db_manager().get_connection()

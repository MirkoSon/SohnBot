# Persistence Layer - SQLite database and audit logging

from .db import DatabaseManager, get_db, get_db_manager, set_db_manager
from .audit import log_operation_start, log_operation_end
from .notification import (
    enqueue_notification,
    get_pending_notifications,
    mark_notification_sent,
    mark_notification_failed,
    requeue_notification,
    schedule_notification_retry,
    get_notifications_enabled,
    set_notifications_enabled,
    get_notification_lag_seconds,
)
from .postponement import (
    save_pending_operation,
    mark_operation_postponed,
    mark_operation_resolved,
    mark_retry_enqueued,
    mark_operation_cancelled,
    get_active_operation_by_chat,
    list_active_operations,
    delete_operation,
)

__all__ = [
    "DatabaseManager",
    "get_db",
    "get_db_manager",
    "set_db_manager",
    "log_operation_start",
    "log_operation_end",
    "enqueue_notification",
    "get_pending_notifications",
    "mark_notification_sent",
    "mark_notification_failed",
    "requeue_notification",
    "schedule_notification_retry",
    "get_notifications_enabled",
    "set_notifications_enabled",
    "get_notification_lag_seconds",
    "save_pending_operation",
    "mark_operation_postponed",
    "mark_operation_resolved",
    "mark_retry_enqueued",
    "mark_operation_cancelled",
    "get_active_operation_by_chat",
    "list_active_operations",
    "delete_operation",
]

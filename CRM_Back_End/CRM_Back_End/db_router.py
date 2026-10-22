import threading
import time

from django.conf import settings


_write_lock = threading.Lock()
_last_write_at = None


class PrimaryReplicaRouter:
    def db_for_read(self, model, **hints):
        lag_window = float(getattr(settings, "DATABASE_REPLICA_LAG_SECONDS", 5))
        with _write_lock:
            if (
                _last_write_at is not None
                and time.monotonic() - _last_write_at < lag_window
            ):
                return "default"

        return "read_replica"

    def db_for_write(self, model, **hints):
        global _last_write_at

        with _write_lock:
            _last_write_at = time.monotonic()

        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._state.db == obj2._state.db:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == "read_replica":
            return False
        return None

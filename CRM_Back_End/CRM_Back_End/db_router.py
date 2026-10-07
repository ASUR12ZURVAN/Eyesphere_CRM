from django.conf import settings


class PrimaryReplicaRouter:
    def db_for_read(self, model, **hints):
        if (
            settings.DATABASE_READ_REPLICA_ENABLED
            and "read_replica" in settings.DATABASES
        ):
            return "read_replica"
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, **hints):
        if db == "read_replica":
            return False
        return None

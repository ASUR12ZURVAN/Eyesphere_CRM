class PrimaryReplicaRouter:
    def db_for_read(self, model, **hints):
        return "read_replica"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, **hints):
        if db == "read_replica":
            return False
        return None

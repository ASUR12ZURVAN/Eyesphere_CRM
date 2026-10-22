from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from CRM_Back_End import db_router
from CRM_Back_End.db_router import PrimaryReplicaRouter


class PrimaryReplicaRouterTests(SimpleTestCase):
    @override_settings(DATABASE_REPLICA_LAG_SECONDS=5)
    def test_reads_use_primary_during_replica_lag_window(self):
        router = PrimaryReplicaRouter()

        with (
            patch.object(db_router, "_last_write_at", None),
            patch(
                "CRM_Back_End.db_router.time.monotonic",
                side_effect=[100, 104, 106],
            ),
        ):
            self.assertEqual(router.db_for_read(None), "read_replica")
            self.assertEqual(router.db_for_write(None), "default")
            self.assertEqual(router.db_for_read(None), "default")
            self.assertEqual(router.db_for_read(None), "read_replica")

    def test_replica_is_never_used_for_migrations(self):
        router = PrimaryReplicaRouter()

        self.assertFalse(router.allow_migrate("read_replica", "lead"))
        self.assertIsNone(router.allow_migrate("default", "lead"))

    def test_relations_between_different_databases_are_not_allowed(self):
        router = PrimaryReplicaRouter()

        class State:
            def __init__(self, database):
                self.db = database

        class Model:
            def __init__(self, database):
                self._state = State(database)

        self.assertTrue(router.allow_relation(Model("default"), Model("default")))
        self.assertIsNone(
            router.allow_relation(Model("default"), Model("read_replica"))
        )

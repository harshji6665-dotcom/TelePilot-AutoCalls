from datetime import UTC, datetime, timedelta
import secrets
import time

from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

from .timeutils import now


class Store:
    def __init__(self, config):
        self.client = AsyncMongoClient(
            config.mongo_uri.get_secret_value(),
            tz_aware=True,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
            timeoutMS=20000,
            waitQueueTimeoutMS=5000,
        )
        self.db = self.client[config.mongo_database]
        self.instance = secrets.token_hex(16)
        self.config = config
        self.lease_fence_enabled = False  # Runtime enables it before any account clients.
        self.lease_deadline = 0.0
        self.lease_fence_closed = False

    async def initialize(self):
        await self.client.admin.command("ping")
        await self.db.jobs.create_index([("status", 1), ("run_at", 1)])
        await self.db.jobs.create_index([("user_id", 1), ("created_at", -1)])
        await self.db.accounts.create_index("telegram_id", unique=True)
        await self.db.targets.create_index([("user_id", 1), ("chat_id", 1)], unique=True)
        await self.db.targets.create_index([("user_id", 1), ("created_at", 1), ("_id", 1)])
        await self.db.outbox.create_index([("status", 1), ("run_at", 1)])
        await self.db.outbox.create_index("event_key", unique=True)
        await self.db.outbox.create_index("purge_at", expireAfterSeconds=0)
        await self.db.login_tickets.create_index("expires_at", expireAfterSeconds=0)
        await self.db.audit.create_index("purge_at", expireAfterSeconds=0)
        await self.db.audit.create_index("created_at")
        await self.db.jobs.create_index("purge_at", expireAfterSeconds=0)
        await self.db.ui_panels.create_index("purge_at", expireAfterSeconds=0)
        await self.db.users.create_index([("plan.expires_at", 1), ("expiry_notified", 1)])
        await self.db.users.create_index("created_at")
        await self.db.accounts.create_index([("enabled", 1), ("status", 1)])
        await self.db.jobs.create_index([("target_id", 1), ("status", 1)])

        await self.db.force_subs.create_index("created_at")
        await self.db.targets.create_index("auto_call.enabled")
        await self.db.targets.create_index(
            "chat_id", unique=True, partialFilterExpression={"auto_call.enabled": True}, name="one_auto_owner_per_chat"
        )
        await self.db.auto_sessions.create_index([("user_id", 1), ("created_at", 1)])
        await self.db.auto_sessions.create_index([("target_id", 1), ("assigned_count", 1)])
        await self.db.auto_sessions.create_index("purge_at", expireAfterSeconds=0)

    async def migrate_plans(self):
        """Idempotent, leader-only legacy migration; never erase data or shrink access."""
        await self.db.users.update_many(
            {"plan.expires_at": {"$exists": True}, "plan.feature_plan": {"$exists": False}}, {"$set": {"plan.feature_plan": "both"}}
        )
        async for user in self.db.users.find({"plan.expires_at": {"$exists": True}, "plan.channel_limit": {"$exists": False}}):
            count = await self.db.targets.count_documents({"user_id": user["_id"]})
            await self.db.users.update_one(
                {"_id": user["_id"], "plan.channel_limit": {"$exists": False}},
                {"$set": {"plan.channel_limit": max(10, count), "plan.schema_version": 2}},
            )
        staff = set(self.config.owner_ids)
        async for row in self.db.admins.find({}):
            staff.add(row["_id"])
        await self.db.targets.update_many(
            {"user_id": {"$nin": list(staff)}, "locked": {"$ne": True}}, {"$set": {"locked": True, "locked_at": now()}}
        )

    def lease_valid(self):
        return not self.lease_fence_closed and time.monotonic() < self.lease_deadline

    def fence(self):
        self.lease_fence_closed = True
        self.lease_deadline = 0.0

    async def acquire_leader(self) -> bool:
        if self.lease_fence_closed:
            return False
        started = time.monotonic()
        leases = self.db.leases.with_options(write_concern=WriteConcern("majority", wtimeout=5000))
        # Seed separately: Mongo does not permit $expr in an upsert predicate.
        # The actual claim/renewal below is one server-clock atomic operation.
        try:
            await leases.update_one(
                {"_id": "runtime"}, {"$setOnInsert": {"holder": "", "until": datetime(1970, 1, 1, tzinfo=UTC)}}, upsert=True
            )
        except DuplicateKeyError:
            pass
        result = await leases.find_one_and_update(
            {"_id": "runtime", "$or": [{"holder": self.instance}, {"$expr": {"$lte": ["$until", "$$NOW"]}}]},
            [{"$set": {"holder": self.instance, "until": {"$add": ["$$NOW", 90000]}, "renewed_at": "$$NOW", "fence_protocol": 2}}],
            return_document=ReturnDocument.AFTER,
        )
        if result and result["holder"] == self.instance and not self.lease_fence_closed:
            self.lease_deadline = started + 70  # Stop writes BEFORE the 90 s server lease can expire.
            return self.lease_valid()
        self.lease_deadline = 0.0
        return False

    async def release_leader(self):
        self.fence()
        await self.db.leases.delete_one({"_id": "runtime", "holder": self.instance})

    async def close(self):
        await self.client.close()

    async def audit(self, actor: int, action: str, **details):
        # Callers pass only bounded identifiers and status metadata, never secrets/links.
        await self.db.audit.insert_one(
            {
                "actor": actor,
                "action": action,
                "details": details,
                "created_at": now(),
                "purge_at": now() + timedelta(days=self.config.audit_retention_days),
            }
        )

    async def touch_user(self, user_id: int, username: str | None):
        await self.db.users.update_one(
            {"_id": user_id}, {"$set": {"username": username, "last_seen": now()}, "$setOnInsert": {"created_at": now()}}, upsert=True
        )

    async def setting(self, key: str, default=None):
        row = await self.db.settings.find_one({"_id": key})
        return row["value"] if row else default

    async def set_setting(self, key: str, value):
        await self.db.settings.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

import os
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cryptography.fernet import Fernet
import pytest

from app.config import Config
from app.notifier import Notifier
from app.security import Vault
from app.services import Access, Plans, Targets
from app.accounts import AccountPool
from app.login import LoginManager
from app.jobs import JobEngine
from app.store import Store


@pytest.fixture
def config():
    return Config.model_validate(
        {
            "api_id": 12345,
            "api_hash": "a" * 32,
            "bot_token": "123456789:" + "b" * 35,
            "mongo_uri": os.getenv("TEST_MONGO_URI", "mongodb://127.0.0.1:27018"),
            "mongo_database": "telepilot_test_" + secrets.token_hex(6),
            "owner_ids": [111],
            "session_encryption_key": Fernet.generate_key().decode(),
            "public_base_url": "https://portal.test",
            "ui_edit_panels": False,  # Legacy handler assertions; dedicated UI suite tests edited transport.
            "ui_style": "plain",
        }
    )


@pytest.fixture
async def store(config):
    if not os.getenv("TEST_MONGO_URI"):
        pytest.skip("Set TEST_MONGO_URI to a disposable MongoDB to run integration tests")
    database = Store(config)
    await database.initialize()
    try:
        yield database
    finally:
        await database.client.drop_database(config.mongo_database)
        await database.close()


@pytest.fixture
async def runtime(store, config):
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        get_me=AsyncMock(return_value=SimpleNamespace(id=999)),
        get_chat=AsyncMock(),
        get_chat_member=AsyncMock(),
        create_chat_invite_link=AsyncMock(),
        revoke_chat_invite_link=AsyncMock(),
    )
    access = Access(store, config)
    notifier = Notifier(store, bot, config)
    pool = AccountPool(store, access, Vault(config.session_encryption_key.get_secret_value()), notifier, config)
    targets = Targets(store, bot, access, 999)
    plans = Plans(store, access, notifier, config)
    login = LoginManager(store, access, pool, notifier, config)
    jobs = JobEngine(store, access, targets, pool, notifier, config)
    result = SimpleNamespace(
        store=store,
        config=config,
        bot=bot,
        access=access,
        notifier=notifier,
        pool=pool,
        targets=targets,
        plans=plans,
        login=login,
        jobs=jobs,
        ready=True,
        stopping=False,
        tasks=[],
        compat=SimpleNamespace(check=AsyncMock(return_value="ok")),
    )
    yield result
    if getattr(result, "health", None):
        await result.health.close()
    if getattr(result, "auto_calls", None):
        await result.auto_calls.close()
    await login.close()
    await jobs.close()
    await pool.close()

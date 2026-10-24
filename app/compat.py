from datetime import timedelta
import hashlib
import importlib.metadata
import inspect

import httpx
from packaging.version import Version

from .security import html
from .timeutils import now

PACKAGES = ("Telethon", "aiogram", "py-tgcalls", "ntgcalls", "pymongo")


def local_compatibility(calls_enabled=True):
    from telethon import errors, functions, TelegramClient
    from telethon.network.mtprotosender import MTProtoSender
    from pymongo import AsyncMongoClient

    assert AsyncMongoClient is not None
    assert importlib.metadata.version("Telethon") == "1.45.0"
    assert "ordered" in inspect.signature(MTProtoSender.send).parameters
    assert hasattr(MTProtoSender, "_keepalive_ping") and hasattr(MTProtoSender, "_disconnected")
    assert hasattr(TelegramClient, "_handle_auto_reconnect")
    assert hasattr(errors, "InviteRequestSentError")
    assert "hash" in inspect.signature(functions.messages.ImportChatInviteRequest).parameters
    assert "channel" in inspect.signature(functions.channels.JoinChannelRequest).parameters
    if calls_enabled:
        from pytgcalls import PyTgCalls
        from pytgcalls.types import GroupCallConfig, ChatUpdate

        assert "auto_start" in inspect.signature(GroupCallConfig).parameters
        assert hasattr(PyTgCalls, "play") and hasattr(PyTgCalls, "leave_call")
        assert hasattr(ChatUpdate.Status, "KICKED")
        # Native callback ownership depends on this pinned internal bridge shape.
        # New releases are advisory only; never auto-upgrade this integration.
        from ntgcalls import NTgCalls
        from .native_lifecycle import CALLBACK_METHODS

        assert importlib.metadata.version("py-tgcalls") == "3.0.0"
        assert importlib.metadata.version("ntgcalls") == "3.0.3"
        assert hasattr(PyTgCalls, "_handle_mtproto_updates")
        for callback, path in CALLBACK_METHODS.items():
            assert hasattr(NTgCalls, callback)
            if not path.startswith("_app."):
                assert hasattr(PyTgCalls, path)
    return "Local adapter/API signature checks passed."


class Compatibility:
    def __init__(self, store, notifier, config):
        self.store, self.notifier, self.config = store, notifier, config

    async def check(self, notify=True):
        lines = [local_compatibility(self.config.calls_enabled)]
        async with httpx.AsyncClient(timeout=8, trust_env=False, follow_redirects=False) as client:
            for name in PACKAGES:
                if not self.config.calls_enabled and name in ("py-tgcalls", "ntgcalls"):
                    continue
                installed = importlib.metadata.version(name)
                try:
                    response = await client.get(f"https://pypi.org/pypi/{name}/json")
                    response.raise_for_status()
                    latest = response.json()["info"]["version"]
                    newer = Version(latest) > Version(installed) and not Version(latest).is_prerelease
                    lines.append(f"{name}: installed {installed}; latest stable {latest}" + (" — UPDATE AVAILABLE" if newer else ""))
                except Exception as exc:
                    lines.append(f"{name}: installed {installed}; registry check unavailable ({type(exc).__name__})")
        report = "\n".join(lines)
        signature = hashlib.sha256(report.encode()).hexdigest()
        previous = await self.store.setting("compat_signature")
        await self.store.set_setting(
            "compat_report",
            {"text": report, "checked_at": now(), "next_check": now() + timedelta(hours=self.config.compatibility_check_hours)},
        )
        if notify and signature != previous:
            await self.notifier.owners(
                "<b>Compatibility check</b>\n<blockquote>"
                + html(report[:3400])
                + "</blockquote>\nNo live code was changed. Test, update pins and rebuild manually.",
                "compat:" + signature,
            )
        await self.store.set_setting("compat_signature", signature)
        return report

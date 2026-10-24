from dataclasses import dataclass
import re
from urllib.parse import parse_qs, unquote, urlparse

from .security import UserError


@dataclass(frozen=True)
class TelegramLink:
    kind: str  # public, invite
    value: str
    invite_hash: str | None = None  # optional speaker token, not membership invite

    @property
    def identity(self):
        return self.kind, self.value.lower() if self.kind == "public" else self.value


USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}\Z")
INVITE = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
RESERVED = {"call", "c", "s", "addlist", "share", "proxy", "socks", "login", "iv", "boost"}


def parse_link(text: str) -> TelegramLink:
    text = text.strip()
    if len(text) > 512 or any(c.isspace() for c in text):
        raise UserError("Please send one valid Telegram channel/group link.")
    if text.startswith("@"):
        name = text[1:]
        if not USERNAME.fullmatch(name):
            raise UserError("Invalid Telegram username.")
        return TelegramLink("public", name)
    if text.startswith(("t.me/", "telegram.me/")):
        text = "https://" + text
    try:
        parsed = urlparse(text)
        port = parsed.port
    except ValueError:
        raise UserError("Invalid Telegram URL.") from None
    if parsed.scheme == "tg":
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.netloc == "call":
            raise UserError(
                "E2E conference links (t.me/call/...) are not supported by this adapter. Use a group/channel voice-video-chat link."
            )
        if parsed.netloc == "join":
            value = query.get("invite", [""])[0]
            kind = "invite"
        elif parsed.netloc == "resolve":
            value = query.get("domain", [""])[0]
            kind = "public"
        else:
            raise UserError("Unsupported Telegram deep link.")
    elif parsed.scheme == "https" and parsed.hostname in ("t.me", "telegram.me", "www.t.me"):
        if parsed.username or parsed.password or port or parsed.fragment:
            raise UserError("Invalid Telegram URL.")
        parts = unquote(parsed.path).strip("/").split("/")
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parts[0] == "call":
            raise UserError("E2E conference links (t.me/call/...) are not supported. Use a group/channel voice-video-chat link.")
        if len(parts) == 2 and parts[0] == "joinchat":
            kind, value = "invite", parts[1]
        elif len(parts) == 1 and parts[0].startswith("+"):
            kind, value = "invite", parts[0][1:]
        elif len(parts) == 1 and parts[0] not in RESERVED:
            kind, value = "public", parts[0]
        else:
            raise UserError("Use a group/channel invite, not a message, folder or conference link.")
    else:
        raise UserError("Only https://t.me links, @usernames or supported tg:// links are accepted.")
    matcher = USERNAME if kind == "public" else INVITE
    if not matcher.fullmatch(value):
        raise UserError("Invalid Telegram group/channel link.")
    unknown = set(query) - {"voicechat", "videochat", "livestream"}
    # tg:// has one extra identity query parameter.
    unknown -= {"invite"} if parsed.netloc == "join" else {"domain"} if parsed.netloc == "resolve" else set()
    if unknown:
        raise UserError("Unsupported link parameters; send the plain invite or voice/video-chat link.")
    speakers = [v for k in ("voicechat", "videochat", "livestream") for v in query.get(k, []) if v]
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) for v in speakers) or len(speakers) > 1:
        raise UserError("Invalid call invite token.")
    return TelegramLink(kind, value, speakers[0] if speakers else None)

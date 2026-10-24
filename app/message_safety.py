"""Conservative Telegram text bounds without slicing HTML tags/entities."""

from html import escape
from html.parser import HTMLParser


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"blockquote", "pre", "p", "div"}:
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")


def utf16_length(text):
    return len(text.encode("utf-16-le", errors="replace")) // 2


def plain_html(text, maximum=3800):
    parser = PlainText()
    parser.feed(text)
    parser.close()
    plain = "".join(parser.parts).strip() or "Open the bot to view this update."
    escaped = escape(plain, quote=False)
    if utf16_length(escaped) <= maximum:
        return escaped
    suffix = "… (open the bot for full details)"
    budget = maximum - utf16_length(suffix)
    result = []
    for char in plain:
        piece = escape(char, quote=False)
        size = utf16_length(piece)
        if size > budget:
            break
        result.append(piece)
        budget -= size
    return "".join(result) + suffix


def bounded_html(text, maximum=3800):
    # Count raw markup too: conservative, but safe even for supplementary emoji
    # and HTML entities. Oversized messages lose formatting rather than validity.
    return text if utf16_length(text) <= maximum else plain_html(text, maximum)


def bad_request_category(exc):
    """Inspect only in memory; return a closed allowlist, never Telegram's text."""
    message = str(getattr(exc, "message", "")).lower()
    if any(value in message for value in ("can't parse entities", "cannot parse entities", "unsupported start tag", "can't find end tag")):
        return "html_parse"
    if "message is too long" in message or "message_too_long" in message:
        return "message_too_long"
    if "chat not found" in message:
        return "chat_not_found"
    if "button_data_invalid" in message or "button_url_invalid" in message or "reply markup" in message:
        return "invalid_keyboard"
    if "not enough rights" in message or "chat_write_forbidden" in message:
        return "write_forbidden"
    return "unknown_bad_request"

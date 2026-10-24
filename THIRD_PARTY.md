# Third-party dependencies

Dependencies are downloaded from their package registries during installation; this ZIP does not embed their native wheels/source. The full resolved versions are pinned in `requirements.txt`.

Principal dependencies: Telethon (MTProto), aiogram (Bot API), PyTgCalls and NTgCalls (native Telegram RTC; LGPL-family licenses), PyMongo (async Mongo), FastAPI/Starlette/Uvicorn (HTTPS portal backend), cryptography (Fernet), httpx, Pydantic, qrcode/pypng (local QR PNG renderer) and supporting packages. Their own licenses/notices apply and remain in installed package metadata. Docker base images and FFmpeg have separate licenses. Review upstream license obligations if redistributing built binaries or modifying dependency libraries.

Useful references:
- https://docs.telethon.dev/en/stable/
- https://github.com/pytgcalls/pytgcalls
- https://pytgcalls.github.io/
- https://docs.aiogram.dev/
- https://www.mongodb.com/docs/languages/python/pymongo-driver/current/
- https://core.telegram.org/api/links
- https://core.telegram.org/api/terms

The supplied default start image was fetched from the user's specified URL without generating a replacement. Use it only if you have the right to deploy it. No ownership claim over that image is made by this project.

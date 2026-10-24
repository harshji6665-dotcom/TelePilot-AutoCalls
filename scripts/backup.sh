#!/usr/bin/env sh
set -eu
# Dumps ciphertext-bearing Mongo data, not plaintext sessions. Protect the backup and .env separately.
mkdir -p backups
chmod 700 backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T mongo sh -c 'mongodump --quiet --username root --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db telepilot --archive --gzip' > "backups/telepilot-${stamp}.archive.gz"
chmod 600 "backups/telepilot-${stamp}.archive.gz"
printf 'Database backup saved. Store the original SESSION_ENCRYPTION_KEY separately in a password manager.\n'

#!/bin/sh
set -eu
umask 077

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
mkdir -p backups
backup_path="backups/docsproject-$(date -u +%Y%m%dT%H%M%SZ).dump"
partial_path="$backup_path.part"
trap 'rm -f "$partial_path"' EXIT HUP INT TERM

docker compose --env-file .env.production -f compose.production.yaml exec -T db \
    sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
    > "$partial_path"
test -s "$partial_path"
mv "$partial_path" "$backup_path"
printf 'Backup created: %s\n' "$backup_path"

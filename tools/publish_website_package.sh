#!/usr/bin/env bash
set -euo pipefail

archive=$1
record="$archive.txt"
commit_record=${2:-}
archive_name=${archive##*/}
record_name=${record##*/}
if [[ ! -s "$archive" || ! -s "${commit_record:-$record}" ]]; then
    echo "::error::Expected a non-empty archive and build record at $archive."
    exit 1
fi

: "${SFTP_HOST:?Missing SFTP_HOST secret}"
: "${SFTP_KNOWN_HOSTS:?Missing SFTP_KNOWN_HOSTS secret}"
: "${SFTP_PRIVATE_KEY:?Missing SFTP_PRIVATE_KEY secret}"

publish_temp=$(mktemp -d)
unset SSH_AGENT_PID SSH_AUTH_SOCK
trap '
    if [[ -n "${SSH_AGENT_PID:-}" ]]; then
        ssh-agent -k >/dev/null || true
    fi
    rm -rf -- "$publish_temp"
' EXIT

if command -v sha256sum >/dev/null; then
    digest=$(sha256sum -- "$archive")
else
    digest=$(shasum -a 256 -- "$archive")
fi
digest=${digest%% *}
if [[ -n "$commit_record" ]]; then
    record="$publish_temp/$record_name"
    {
        printf 'sha256=%s\n' "$digest"
        tr -d '\r' < "$commit_record"
    } > "$record"
fi
commit=$(tr -d '\r' < "$record" | sed -n 's/^commit=//p')
checksum=$(tr -d '\r' < "$record" | sed -n 's/^sha256=//p')
if [[ "$checksum" != "$digest" || "$commit" != "$GITHUB_SHA" ]]; then
    echo "::error::The archive or build record does not match the current commit."
    exit 1
fi

agent_environment=$(ssh-agent -a "$publish_temp/agent" -s)
eval "$agent_environment" >/dev/null
printf '%s\n' "$SFTP_PRIVATE_KEY" | tr -d '\r' | ssh-add -
unset SFTP_PRIVATE_KEY
printf '%s\n' "$SFTP_KNOWN_HOSTS" > "$publish_temp/known_hosts"

remote_dir=${SFTP_REMOTE_DIR:-/usr/share/nginx/html/tools/BluraySubtitle}
destination="${SFTP_USER:-bluray-deploy}@$SFTP_HOST"
sftp_options=(
    -b - -P "${SFTP_PORT:-22}"
    -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=\"$publish_temp/known_hosts\""
)
remote_files=$(printf '@cd "%s"\n@ls -1\n' "$remote_dir" |
    sftp "${sftp_options[@]}" "$destination" | tr -d '\r')

# The publisher is serialized per package. An interrupted upload can reuse these names.
staged_archive=".$archive_name.part"
staged_record=".$record_name.part"
{
    printf 'cd "%s"\n' "$remote_dir"
    printf 'put "%s" "%s"\n' "$archive" "$staged_archive"
    printf 'put "%s" "%s"\n' "$record" "$staged_record"
    printf 'chmod 644 "%s"\n' "$staged_archive" "$staged_record"
    # Remove the previous record before replacing its archive.
    if grep -Fxq "$record_name" <<< "$remote_files"; then
        printf 'rm "%s"\n' "$record_name"
    fi
    printf 'rename "%s" "%s"\n' "$staged_archive" "$archive_name"
    printf 'rename "%s" "%s"\n' "$staged_record" "$record_name"
} | sftp "${sftp_options[@]}" "$destination"

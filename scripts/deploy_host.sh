#!/usr/bin/env bash
# Installed outside release sources and invoked by a restricted SSH deploy key.
set -euo pipefail
release_sha=${SSH_ORIGINAL_COMMAND:-}
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a commit SHA' >&2; exit 2; }
app_root=${LANDSCAPES_DEPLOY_ROOT:-/home/noah/lost-landscapes}
export LANDSCAPES_ENV_FILE="$app_root/.env"
exec 9>"$app_root/.deploy.lock"
flock -w 1200 9
release_dir=$(mktemp -d "$app_root/releases/${release_sha}.XXXXXX")
archive="$release_dir/source.tar.gz"
cat > "$archive"
# Archives come from git archive in the protected-master workflow.
tar -xzf "$archive" -C "$release_dir"
image="lost-landscapes:$release_sha"
docker build -t "$image" -f "$release_dir/Dockerfile.cpu" "$release_dir"
previous_image=$(docker inspect lost-landscapes-api-1 --format '{{.Config.Image}}' 2>/dev/null || true)
compose=(docker compose --project-directory "$app_root" --env-file "$app_root/.env" -f "$release_dir/compose.cpu.yml")
if LANDSCAPES_IMAGE="$image" "${compose[@]}" up -d --no-build --wait --wait-timeout 120 && \
   curl --fail --silent --show-error --retry 6 --retry-all-errors --retry-delay 5 http://127.0.0.1:9750/api/health; then
  printf '%s\n' "$release_sha" > "$app_root/deployed-commit"
  echo "Deployed $release_sha"
else
  echo 'Deployment failed; restoring previous image' >&2
  if [[ -n "$previous_image" ]]; then
    LANDSCAPES_IMAGE="$previous_image" "${compose[@]}" up -d --no-build --wait --wait-timeout 120
  fi
  exit 1
fi

#!/usr/bin/env bash
# Set up or update AgentHire on the server (Ubuntu 24.04). deploy/push.sh copies this file,
# the built site and the .env to the server and runs it there; it can be run again safely.
#
#   sudo bash setup.sh <site host name>      e.g. 13-233-10-20.sslip.io
#
# Installs Python 3.12, Caddy and git; clones (or pulls) the public repository into
# /srv/agenthire/app; installs the Python packages; downloads the voice models; installs two
# systemd services (the back end, and the voice worker, which restarts itself if it stops);
# and serves the site over HTTPS with an automatic Let's Encrypt certificate.
set -euo pipefail

HOST="${1:?usage: sudo bash setup.sh <site host name>}"
REPO="https://github.com/sanithvarma0/agenthire.git"
ROOT=/srv/agenthire
APP=$ROOT/app
STAGE=/tmp/agenthire-upload   # where push.sh put the .env and the built site

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3.12 python3.12-venv git caddy curl

id -u agenthire >/dev/null 2>&1 || useradd --system --home "$ROOT" --shell /usr/sbin/nologin agenthire
mkdir -p "$ROOT"
if [ -d "$APP/.git" ]; then
  # The folder belongs to the agenthire user and this runs as root, so git calls it
  # "dubious ownership" and refuses; inside `&&` that failure was swallowed and a redeploy
  # restarted the old code. Trust the folder, and fail loudly if the update fails.
  git config --global --add safe.directory "$APP"
  git -C "$APP" fetch -q origin main
  git -C "$APP" reset -q --hard origin/main
  echo "Code: $(git -C "$APP" log --oneline -1)"
else
  git clone -q "$REPO" "$APP"
fi
install -m 600 "$STAGE/.env" "$APP/.env"
rm -rf "$ROOT/web" && cp -r "$STAGE/dist" "$ROOT/web"
mkdir -p "$APP/data"

# Python packages, from pyproject.toml's list (no build step needed).
[ -x "$APP/.venv/bin/python" ] || python3.12 -m venv "$APP/.venv"
python3.12 - "$APP/pyproject.toml" > /tmp/agenthire-requirements.txt <<'PY'
import sys, tomllib
print("\n".join(tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]))
PY
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r /tmp/agenthire-requirements.txt
chown -R agenthire:agenthire "$ROOT"
# The voice worker's speech-detection and turn models, fetched once ahead of the first call.
sudo -u agenthire bash -c "cd $APP && .venv/bin/python -m voice.worker download-files"

cat > /etc/systemd/system/agenthire-backend.service <<UNIT
[Unit]
Description=AgentHire back end
After=network-online.target
Wants=network-online.target

[Service]
User=agenthire
WorkingDirectory=$APP
EnvironmentFile=$APP/.env
Environment=PYTHONIOENCODING=utf-8
ExecStart=$APP/.venv/bin/python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/agenthire-worker.service <<UNIT
[Unit]
Description=AgentHire voice worker (LiveKit)
After=agenthire-backend.service
Wants=agenthire-backend.service

[Service]
User=agenthire
WorkingDirectory=$APP
EnvironmentFile=$APP/.env
Environment=PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
ExecStart=$APP/.venv/bin/python -m voice.worker start
# LiveKit gives up after about two minutes without a connection; come straight back.
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

# The site and the API on one HTTPS origin. Only the paths the browser uses are passed to
# the back end: /conversations and /events POST are the worker's (it calls the back end
# directly), and /dev is test-mode tooling, never exposed.
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
	encode gzip
	@api {
		path /jobs /jobs/* /roles /roles/* /location /location/* /providers/* /health /mode
	}
	@stream {
		path /events/stream
		method GET
	}
	handle @stream {
		reverse_proxy 127.0.0.1:8000 {
			flush_interval -1
		}
	}
	handle @api {
		reverse_proxy 127.0.0.1:8000
	}
	handle {
		root * $ROOT/web
		try_files {path} /index.html
		file_server
	}
}
CADDY

systemctl daemon-reload
systemctl enable -q agenthire-backend agenthire-worker caddy
systemctl restart agenthire-backend
sleep 3
systemctl restart agenthire-worker
systemctl reload caddy || systemctl restart caddy
rm -rf "$STAGE"
echo "AgentHire is running at https://$HOST"

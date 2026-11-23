#!/bin/sh
# Usage: MAC_HOST=<Mac LAN address> [MAC_USER=<account>] [SLEEP_AT=23:00] [WAKE_AT=07:00] deploy/install.sh
# Fills the __PLACEHOLDERS__ in deploy/ and kindle/, installs the launchd service on this Mac,
# and copies the Kindle files over `ssh kindle` (the jailbroken Kindle must already be reachable).
set -eu

: "${MAC_HOST:?set MAC_HOST to the Mac mini LAN address the Kindle connects to}"
MAC_USER=${MAC_USER:-$(id -un)}
SLEEP_AT=${SLEEP_AT:-23:00}
WAKE_AT=${WAKE_AT:-07:00}
PROJECT_DIR=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

render() {
  mkdir -p "$OUT/$(dirname "$1")"
  sed -e "s|__MAC_HOST__|$MAC_HOST|g" -e "s|__MAC_USER__|$MAC_USER|g" \
      -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" -e "s|__SLEEP_AT__|$SLEEP_AT|g" \
      -e "s|__WAKE_AT__|$WAKE_AT|g" "$PROJECT_DIR/$1" > "$OUT/$1"
}
cd "$PROJECT_DIR"
find deploy kindle -type f ! -name install.sh | while read -r f; do render "$f"; done

PLIST="$HOME/Library/LaunchAgents/local.kindle-dash.plist"
mkdir -p logs
if ! cmp -s "$OUT/deploy/local.kindle-dash.plist" "$PLIST"; then
  cp "$OUT/deploy/local.kindle-dash.plist" "$PLIST"
  launchctl bootout "gui/$(id -u)/local.kindle-dash" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
fi
launchctl kickstart -k "gui/$(id -u)/local.kindle-dash"

K="$OUT/kindle"
ssh kindle 'mkdir -p /mnt/us/kindle-dash /var/local/kindle-dash /var/local/mesquite/kindledash /tmp/kindle-dash-upstart'
scp -q "$K/scripts/start.sh" "$K/scripts/stop.sh" kindle:/mnt/us/kindle-dash/
scp -q "$K/scripts/tunnel.sh" "$K/scripts/night.sh" kindle:/var/local/kindle-dash/
scp -q "$K/library/Dashboard.sh" "$K/library/Dashboard - allow sleep.sh" kindle:/mnt/us/documents/
scp -q "$K/app/config.xml" "$K/app/index.html" kindle:/var/local/mesquite/kindledash/
scp -q "$K"/upstart/*.conf kindle:/tmp/kindle-dash-upstart/
ssh kindle 'set -e
chmod 755 /mnt/us/kindle-dash/*.sh /var/local/kindle-dash/*.sh /mnt/us/documents/Dashboard*.sh
chown -R "$(stat -c %u:%g /var/local/mesquite/webview)" /var/local/mesquite/kindledash
ID=dev.kindledash
sqlite3 /var/local/appreg.db "insert or ignore into handlerIds(handlerId) values(\"$ID\");
insert or replace into properties(handlerId,name,value) values(\"$ID\",\"command\",\"/usr/bin/mesquite -l $ID -c file:///var/local/mesquite/kindledash/\");
insert or replace into properties(handlerId,name,value) values(\"$ID\",\"framework\",\"\");
insert or replace into properties(handlerId,name,value) values(\"$ID\",\"unloadPolicy\",\"unloadOnPause\");
insert or replace into associations(handlerId,interface,contentId,defaultAssoc) values(\"$ID\",\"application\",\"none\",\"false\");"
mntroot rw >/dev/null
cp /tmp/kindle-dash-upstart/*.conf /etc/upstart/
mntroot ro >/dev/null'
echo "installed: service local.kindle-dash, Kindle app $MAC_HOST:8090, tunnel as $MAC_USER@$MAC_HOST, night $SLEEP_AT-$WAKE_AT"

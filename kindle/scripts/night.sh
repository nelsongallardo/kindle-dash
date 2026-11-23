#!/bin/sh
SLEEP_AT=${SLEEP_AT:-__SLEEP_AT__}
WAKE_AT=${WAKE_AT:-__WAKE_AT__}
P=com.lab126.powerd
ASLEEP=/tmp/kindle-dash-asleep

secs_until() {
  now=$(date +%s)
  t=$(date -d "$(date +%Y-%m-%d) $1" +%s)
  [ "$t" -le "$now" ] && t=$((t + 86400))
  echo $((t - now))
}

in_night() {
  [ "$(secs_until "$WAKE_AT")" -lt "$(secs_until "$SLEEP_AT")" ] && [ "$(secs_until "$WAKE_AT")" -gt 120 ]
}

log() { echo "$(date '+%F %T') $*"; }

sleep_until_morning() {
  log "sleeping until $WAKE_AT (battery $(lipc-get-prop $P battLevel)%)"
  touch $ASLEEP
  pkill -f "dropbearmulti dbclient"
  lipc-set-prop $P preventScreenSaver 0
  [ "$(lipc-get-prop $P status | head -1)" = "Powerd state: Screen Saver" ] || lipc-set-prop $P powerButton 1
  while true; do
    ev=$(lipc-wait-event $P readyToSuspend,wakeupFromSuspend,outOfScreenSaver)
    case "$ev" in
      readyToSuspend*) lipc-set-prop $P rtcWakeup "$(secs_until "$WAKE_AT")" ;;
      outOfScreenSaver*) log "event: $ev"; rm -f $ASLEEP; return 1 ;;
      wakeupFromSuspend*) log "event: $ev"; in_night || break ;;
    esac
  done
  rm -f $ASLEEP
  lipc-set-prop $P wakeUp 1
  return 0
}

while true; do
  if in_night; then
    if sleep_until_morning; then
      log "morning wake"
      /mnt/us/kindle-dash/start.sh
    else
      log "woken by hand during the night; dashboard for 5 minutes"
      /mnt/us/kindle-dash/start.sh
      sleep 300
    fi
  else
    s=$(secs_until "$SLEEP_AT")
    sleep $((s < 600 ? s : 600))
  fi
done

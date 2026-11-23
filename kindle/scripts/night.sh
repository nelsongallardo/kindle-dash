#!/bin/sh
SLEEP_AT=${SLEEP_AT:-__SLEEP_AT__}
WAKE_AT=${WAKE_AT:-__WAKE_AT__}
PRESENCE_URL=http://__MAC_HOST__:8090/presence
AWAY_CHECK_SECONDS=${AWAY_CHECK_SECONDS:-600}
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

# Only a definite "away" from the server counts; no answer keeps the dashboard on.
away() {
  [ "$(curl -s --max-time 5 "$PRESENCE_URL")" = away ]
}

# Wi-Fi stays off after a timed wake-up until the Kindle is fully awake, so wake it to ask.
presence_after_wake() {
  lipc-set-prop $P wakeUp 1
  for _ in $(seq 1 45); do
    answer=$(curl -s --max-time 2 "$PRESENCE_URL")
    [ -n "$answer" ] && { echo "$answer"; return; }
    sleep 1
  done
}

sleep_reason() {
  if in_night; then echo night; elif away; then echo away; fi
}

# Sleeps until it is day and someone is home (returns 0) or the power button is pressed (returns 1).
doze() {
  reason=$1
  log "sleeping: $reason (battery $(lipc-get-prop $P battLevel)%)"
  touch $ASLEEP
  pkill -f "dropbearmulti dbclient"
  lipc-set-prop $P preventScreenSaver 0
  [ "$(lipc-get-prop $P status | head -1)" = "Powerd state: Screen Saver" ] || lipc-set-prop $P powerButton 1
  while true; do
    ev=$(lipc-wait-event $P readyToSuspend,wakeupFromSuspend,outOfScreenSaver)
    case "$ev" in
      readyToSuspend*)
        if [ "$reason" = night ]; then
          lipc-set-prop $P rtcWakeup "$(secs_until "$WAKE_AT")"
        else
          lipc-set-prop $P rtcWakeup "$AWAY_CHECK_SECONDS"
        fi
        ;;
      outOfScreenSaver*) log "event: $ev"; rm -f $ASLEEP; return 1 ;;
      wakeupFromSuspend*)
        if in_night; then reason=night; continue; fi
        answer=$(presence_after_wake)
        if [ "$answer" = away ]; then
          reason=away
          lipc-set-prop $P powerButton 1
          continue
        fi
        [ -n "$answer" ] || log "no answer from the Mac after waking"
        break
        ;;
    esac
  done
  rm -f $ASLEEP
  return 0
}

while true; do
  reason=$(sleep_reason)
  if [ -n "$reason" ]; then
    if doze "$reason"; then
      log "awake: day and someone is home"
      /mnt/us/kindle-dash/start.sh
    else
      log "woken by hand; dashboard for 5 minutes"
      /mnt/us/kindle-dash/start.sh
      sleep 300
    fi
  else
    sleep 60
  fi
done

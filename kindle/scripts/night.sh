#!/bin/sh
SLEEP_AT=${SLEEP_AT:-__SLEEP_AT__}
WAKE_AT=${WAKE_AT:-__WAKE_AT__}
PRESENCE_URL=http://__MAC_HOST__:8090/presence
AWAY_CHECK_SECONDS=${AWAY_CHECK_SECONDS:-600}
P=com.lab126.powerd
ASLEEP=/tmp/kindle-dash-asleep
BEDTIME_UNTIL=/tmp/kindle-dash-bedtime-until

secs_until() {
  now=$(date +%s)
  t=$(date -d "$(date +%Y-%m-%d) $1" +%s)
  [ "$t" -le "$now" ] && t=$((t + 86400))
  echo $((t - now))
}

in_night() {
  [ "$(secs_until "$WAKE_AT")" -lt "$(secs_until "$SLEEP_AT")" ] && [ "$(secs_until "$WAKE_AT")" -gt 120 ]
}

in_bedtime() {
  [ -s $BEDTIME_UNTIL ] && [ $(($(cat $BEDTIME_UNTIL) - $(date +%s))) -gt 120 ]
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
  if in_night; then echo night; elif in_bedtime; then echo bedtime; elif away; then echo away; fi
}

# Waits $1 seconds, or less if Good night is tapped.
pause() {
  for _ in $(seq 1 "$1"); do
    in_bedtime && return
    sleep 1
  done
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
        if [ "$reason" != away ]; then
          lipc-set-prop $P rtcWakeup "$(secs_until "$WAKE_AT")"
        else
          lipc-set-prop $P rtcWakeup "$AWAY_CHECK_SECONDS"
        fi
        ;;
      outOfScreenSaver*) log "event: $ev"; rm -f $ASLEEP $BEDTIME_UNTIL; return 1 ;;
      wakeupFromSuspend*)
        if in_night; then reason=night; continue; fi
        if in_bedtime; then continue; fi
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
  rm -f $ASLEEP $BEDTIME_UNTIL
  return 0
}

if [ "$1" = bedtime ]; then
  echo $(($(date +%s) + $(secs_until "$WAKE_AT"))) > $BEDTIME_UNTIL.new
  mv $BEDTIME_UNTIL.new $BEDTIME_UNTIL
  exit
fi

while true; do
  reason=$(sleep_reason)
  if [ -n "$reason" ]; then
    if doze "$reason"; then
      log "awake: day and someone is home"
      /mnt/us/kindle-dash/start.sh
    else
      log "woken by hand; dashboard for at least 5 minutes"
      /mnt/us/kindle-dash/start.sh
      pause 300
    fi
  else
    pause 60
  fi
done

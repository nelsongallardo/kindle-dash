#!/bin/sh
D=/var/local/kindle-dash
B=$D/bin/dropbearmulti
MAC=__MAC_HOST__
export HOME=$D/home
if ! netstat -ltn | grep -q "127.0.0.1:2022 "; then
  $B dropbear -r $D/host_key -R -p 127.0.0.1:2022 -s -K 30 -P $D/dropbear.pid
fi
while true; do
  if [ -e /tmp/kindle-dash-asleep ]; then sleep 5; continue; fi
  $B dbclient -N -T -y -K 30 -i $D/tunnel_key -R localhost:2222:127.0.0.1:2022 __MAC_USER__@$MAC
  sleep 15
done

#!/bin/sh
URL=http://__MAC_HOST__:8090/home
lipc-set-prop com.lab126.powerd preventScreenSaver 1
for i in $(seq 1 60); do
  curl -s -o /dev/null --max-time 3 "$URL" && break
  sleep 5
done
lipc-set-prop com.lab126.appmgrd start app://dev.kindledash

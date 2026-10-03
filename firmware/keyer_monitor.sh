#!/bin/bash
# Ping the keyer every 5 s for 12 h; log state changes and a 10-min RTT summary.
HOST=192.168.99.109
LOG="${LOG:-$(dirname "$0")/keyer_monitor.log}"
END=$(( $(date +%s) + 12*3600 ))
state=unknown; down_since=0; rtts=(); fails=0; last_sum=$(date +%s)
echo "$(date '+%F %T') start monitoring $HOST" >> "$LOG"
while [ "$(date +%s)" -lt $END ]; do
  rtt=$(LC_ALL=C ping -c 1 -W 2 $HOST 2>/dev/null | sed -n 's/.*time=\([0-9.]*\).*/\1/p')
  now=$(date +%s)
  if [ -n "$rtt" ]; then
    rtts+=("$rtt"); fails=0
    if [ "$state" != up ]; then
      [ "$state" = down ] && echo "$(date '+%F %T') UP   (down for $(( now - down_since )) s)" >> "$LOG" \
                          || echo "$(date '+%F %T') UP" >> "$LOG"
      state=up
    fi
  else
    fails=$((fails+1))
    # 3 consecutive lost pings (~15 s) = outage
    if [ $fails -eq 3 ] && [ "$state" != down ]; then
      down_since=$(( now - 10 )); state=down
      echo "$(date '+%F %T') DOWN" >> "$LOG"
    fi
  fi
  if [ $(( now - last_sum )) -ge 600 ]; then
    if [ ${#rtts[@]} -gt 0 ]; then
      printf '%s\n' "${rtts[@]}" | sort -n | awk -v t="$(date '+%F %T')" \
        '{a[NR]=$1; s+=$1} END {printf "%s rtt n=%d min=%.0f avg=%.0f max=%.0f ms\n", t, NR, a[1], s/NR, a[NR]}' >> "$LOG"
    else
      echo "$(date '+%F %T') rtt n=0 (no replies)" >> "$LOG"
    fi
    rtts=(); last_sum=$now
  fi
  sleep 5
done
echo "$(date '+%F %T') stop" >> "$LOG"

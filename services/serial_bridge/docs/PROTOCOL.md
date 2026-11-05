# Serial protocol (bridge <-> Arduino)

ASCII, one frame per line, 115200 8N1.

```
$<field>,<field>,...*<CS>\n          CS = XOR of all characters between '$' and '*', 2 upper-case hex digits
```
Fields never contain `$ * , CR LF`. Max frame 96 bytes (firmware buffer 72 bytes of host-to-device).

## Host -> device (commands)
`$CMD,<seq>,<NAME>[,args]*CS` - `seq` 1..65535, chosen by the bridge.

| Command | Meaning | Possible NAK reasons |
|---|---|---|
| `PING` | liveness | |
| `SYNC` | ACK, then device emits a full `STATE` event | |
| `OPEN,<entry\|exit>[,<holdMs 500..60000>]` | open barrier; auto-closes after hold AND gate clear for `clear_ms` | `BAD_GATE` `BAD_VALUE` `BAD_ARGS` |
| `CLOSE,<gate>` | close now (refused if a vehicle is at the gate) | `VEHICLE_PRESENT` `BAD_GATE` |
| `CFG,<key>,<value>` | runtime config: `gate_thr slot_thr hyst debounce debounce_free median sample_ms hold_ms clear_ms open_deg closed_deg hb_ms dbg` (`median` 1-5, 1 = filter off; `dbg` 1 = stream `DIST`) | `BAD_KEY` `BAD_VALUE` |

## Device -> host
**Replies** (`seq` echoes the command): `$ACK,<seq>,OK[,detail]*CS` or `$NAK,<seq>,<REASON>*CS`.
`detail`: `REFRESHED` (barrier was already open, hold extended) or `DUP` (retransmission recognised, not executed again).
`NAK` with seq 0 = frame itself unusable: `CHECKSUM`, `BAD_FRAME`, `BAD_SEQ`, `TOO_LONG`.

**Events** `$EVT,<n>,<NAME>[,args]*CS` - `n` counts up by 1 per event since boot (wraps 65535 -> 1).

| Event | Args | When |
|---|---|---|
| `BOOT` | `<firmware>` | power-up / reset (opening the USB port resets an Uno) |
| `STATE` | `<s1s2s3s4>,<entry>,<exit>,<entryOpen>,<exitOpen>` e.g. `0100,1,0,0,0` | after BOOT and after `SYNC` |
| `HB` | `<uptimeS>,<same 5 state fields>` | every `hb_ms` (2 s) |
| `SLOT` | `<1..4>,<0\|1>` | debounced occupancy change |
| `GATE` | `<entry\|exit>,<0\|1>` | debounced vehicle arrival / departure |
| `DIST` | `<1..4\|entry\|exit>,<medianCm>,<rawCm>` | only with `dbg=1`, ~every 4th sample per sensor; 65535 = no echo |
| `BARRIER` | `<gate>,<OPENED\|CLOSED>` | servo reached its end position |

## Reliability rules
* **Corruption:** bad checksum -> frame dropped (device replies `NAK,0,CHECKSUM`; bridge logs + counts).
* **Command retry:** no reply within `BRIDGE_ACK_TIMEOUT` (0.6 s) -> resend with the *same* `seq`, up to
  `BRIDGE_ACK_RETRIES` (3) times. The device remembers its last 4 (sequence number, frame checksum) pairs: a byte-identical repeat gets
  `ACK,<seq>,OK,DUP` and is **not executed again**; a different command reusing an old seq is executed. The bridge also starts every connection at a random seq, so a lost ACK never opens a barrier twice.
* **Event duplicates:** bridge drops `(boot epoch, n)` pairs it has already seen (epoch bumps on `BOOT`).
* **Lost events:** `STATE`/`HB` carry the complete picture. The bridge compares each one with what it
  believes (gates, slots) and repairs differences, so a missed `SLOT`/`GATE` event self-heals within 2 s.
  A silent link (no byte for `BRIDGE_LINK_TIMEOUT`, 8 s) is treated as disconnected.
* **Disconnect:** pending commands fail with `SerialDisconnected`; the reader reconnects with backoff
  (1 s doubling to 10 s); on reconnect the bridge runs bring-up (backend slot state, `CFG`s, `SYNC`).

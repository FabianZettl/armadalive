#!/usr/bin/env python3
# ES-DE event hook. install.sh links it into ~/ES-DE/scripts/<event>/; ES-DE passes the game as arguments.
# It records the latest event for ArmadaLive, which runs all the time.
import json, os, sys, time

args = sys.argv[1:] + [""] * 4
event = os.path.basename(os.path.dirname(sys.argv[0]))
runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
os.makedirs(runtime + "/armadalive", exist_ok=True)
if event == "system-select":
    state = dict(event=event, system=args[0], systemName=args[1])
elif event in ("startup", "quit"):
    state = dict(event=event)
else:
    state = dict(event=event, path=args[0], name=args[1], system=args[2], systemName=args[3])
state["t"] = time.time()
tmp = runtime + "/armadalive/state.json.tmp"
open(tmp, "w").write(json.dumps(state))
os.replace(tmp, runtime + "/armadalive/state.json")

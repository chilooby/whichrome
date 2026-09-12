#!/usr/bin/env python3
"""Whichrome - know which Chrome you're driving.

A tiny, dependency-free registry that remembers every Chrome profile connected to
Claude's browser extension, which physical computer each one lives on, and what
you call it. Claude reads this before touching a browser so it never drives a
Chrome on a machine you are not sitting at.

Commands
  device                      Print (and record) this computer's identity.
  scan-profiles               Read Chrome's Local State; record profile -> account map for this computer.
  roster [--connected FILE]   Merge the extension's connected-browser list with the registry.
                              --connected takes the JSON array from list_connected_browsers
                              (a file path, or '-' for stdin). Prints a table plus, with --json,
                              ready-made AskUserQuestion options.
  resolve NAME                Print the deviceId for a nickname, if it is known and connected-capable.
  record --id ID [...]        Save what you learned about a browser (nickname, account, locality...).
  forget ID                   Remove a browser record.
  beacon start|check          Locality proof: serve a nonce on 127.0.0.1 and see if a browser reaches it.
  nicknames                   List every known nickname.

Registry location (first hit wins):
  $WHICHROME_REGISTRY  ->  ~/.whichrome-registry.json

Test / demo overrides (so recorded output need not leak a real machine):
  $WHICHROME_HOSTNAME    reported hostname
  $WHICHROME_DEVICE_KEY  the whole device key
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The registry holds account addresses and machine ids, so it lives in the user's home by
# default, never inside a repo that might get published. Point WHICHROME_REGISTRY at a synced
# folder or a private repo to share it across computers.
DEFAULT_REGISTRY = Path.home() / ".whichrome-registry.json"
LEGACY_REGISTRY = HERE.parent / "registry.json"
SCHEMA_VERSION = 1


# ---------------------------------------------------------------- registry io
def registry_path() -> Path:
    env = os.environ.get("WHICHROME_REGISTRY")
    if env:
        return Path(env)
    if not DEFAULT_REGISTRY.exists() and LEGACY_REGISTRY.exists():
        return LEGACY_REGISTRY  # in-place upgrade for early clones
    return DEFAULT_REGISTRY


def load() -> dict:
    p = registry_path()
    if not p.exists():
        return {"version": SCHEMA_VERSION, "devices": {}, "browsers": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"whichrome: registry at {p} is not valid JSON ({exc}). Fix or delete it.")
    except OSError as exc:
        # A directory, a locked file, a bad permission: all of these are "fix the path",
        # not a stack trace. IsADirectoryError and PermissionError are both OSError.
        raise SystemExit(f"whichrome: could not read the registry at {p} ({exc}). "
                         f"Check WHICHROME_REGISTRY points at a writable file.")
    if not isinstance(data, dict):
        raise SystemExit(f"whichrome: registry at {p} must be a JSON object, found {type(data).__name__}.")
    for field in ("devices", "browsers"):
        if field in data and not isinstance(data[field], dict):
            raise SystemExit(f"whichrome: registry at {p} has a {field!r} that is not an object. Fix or delete it.")
        data.setdefault(field, {})
    for field in ("devices", "browsers"):
        for name, rec in list(data[field].items()):
            if not isinstance(rec, dict):
                raise SystemExit(f"whichrome: registry {field} entry {name!r} is not an object. Fix or delete it.")
    data.setdefault("version", SCHEMA_VERSION)
    return data


def save(data: dict) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = SCHEMA_VERSION
    # Write atomically: two whichrome processes must not leave a half-written registry.
    tmp = p.with_suffix(p.suffix + ".tmp%d" % os.getpid())
    try:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        last = None
        for attempt in range(5):
            try:
                os.replace(tmp, p)
                return
            except PermissionError as exc:  # Windows sharing violation: another reader has it open
                last = exc
                time.sleep(0.15 * (attempt + 1))
        raise last
    except OSError as exc:
        try:
            if tmp.exists():
                tmp.unlink()  # never leave an orphan .tmp behind
        except OSError:
            pass
        raise SystemExit(f"whichrome: could not write the registry at {p} ({exc}). "
                         f"Close anything holding it open and try again.")


def today() -> str:
    return time.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- device identity
def machine_uuid() -> str:
    """A stable per-machine id. Falls back to the hostname when unavailable."""
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
                capture_output=True, text=True, timeout=20,
            ).stdout.strip()
            if out and "UUID" not in out:
                return out.splitlines()[-1].strip()
        elif system == "Darwin":
            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=20,
            ).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            if m:
                return m.group(1)
        else:
            for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                p = Path(candidate)
                if p.exists():
                    return p.read_text().strip()
    except Exception:
        pass
    return ""


def hostname() -> str:
    # WHICHROME_HOSTNAME exists for deterministic tests, demos and CI, where the real
    # machine name must not leak into recorded output.
    return os.environ.get("WHICHROME_HOSTNAME") or socket.gethostname()


def device_key() -> str:
    override = os.environ.get("WHICHROME_DEVICE_KEY")
    if override:
        return override
    host = hostname()
    uid = machine_uuid()
    return f"{host}|{uid}" if uid else host


def ensure_device(data: dict, label: str | None = None) -> str:
    key = device_key()
    dev = data["devices"].setdefault(key, {})
    dev["hostname"] = hostname()
    dev["os"] = platform.system()
    dev.setdefault("label", label or hostname())
    if label:
        dev["label"] = label
    dev.setdefault("chromeProfiles", {})
    dev["lastSeen"] = today()
    return key


# ---------------------------------------------------------------- chrome profiles
def chrome_user_data_dirs() -> list[Path]:
    system = platform.system()
    home = Path.home()
    if system == "Windows":
        base = home / "AppData" / "Local"
        return [base / "Google" / "Chrome" / "User Data",
                base / "Google" / "Chrome Beta" / "User Data",
                base / "BraveSoftware" / "Brave-Browser" / "User Data",
                base / "Microsoft" / "Edge" / "User Data"]
    if system == "Darwin":
        base = home / "Library" / "Application Support"
        return [base / "Google" / "Chrome", base / "BraveSoftware" / "Brave-Browser"]
    return [home / ".config" / "google-chrome", home / ".config" / "chromium"]


def scan_profiles() -> dict:
    """profile directory -> signed-in account, straight from Chrome's Local State."""
    found: dict[str, str] = {}
    for udd in chrome_user_data_dirs():
        ls = udd / "Local State"
        if not ls.exists():
            continue
        try:
            state = json.loads(ls.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        cache = state.get("profile", {}).get("info_cache", {})
        for directory, info in cache.items():
            account = (info.get("user_name") or "").strip()
            name = (info.get("name") or "").strip()
            found[f"{udd.name}/{directory}" if udd.name != "User Data" else directory] = account or f"(no account: {name})"
    return found


# ---------------------------------------------------------------- beacon (locality proof)
def beacon_state_path(nonce: str, port: int) -> Path:
    """Per-probe state file: concurrent probes must not overwrite each other."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", nonce)[:40] or "probe"
    return Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp") / f"whichrome-beacon-{safe}-{port}.json"


def beacon_start(port: int, nonce: str, seconds: int) -> None:
    """Serve a one-shot nonce on loopback. Only a browser on THIS machine can fetch it."""
    import http.server

    state_file = beacon_state_path(nonce, port)
    hits: list = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            # Only a request carrying the nonce counts: any page could hit a bare port.
            if nonce in self.path:
                hits.append({"path": self.path, "ua": self.headers.get("User-Agent", ""), "t": time.time()})
            body = f"<title>whichrome {nonce}</title><h1>whichrome beacon ok</h1><p>{nonce}</p>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            state_file.write_text(json.dumps({"nonce": nonce, "port": port, "hits": hits}), encoding="utf-8")

        def log_message(self, *a):  # silence
            return

    state_file.write_text(json.dumps({"nonce": nonce, "port": port, "hits": []}), encoding="utf-8")
    class Server(http.server.HTTPServer):
        allow_reuse_address = False  # on Windows SO_REUSEADDR lets another process hijack the port

    try:
        srv = Server(("127.0.0.1", port), Handler)
    except OSError as exc:
        print(json.dumps({"error": f"port {port} unavailable: {exc}", "hits": 0, "local": False}))
        sys.exit(4)
    srv.timeout = 1
    print(json.dumps({"listening": f"http://127.0.0.1:{port}/{nonce}", "nonce": nonce, "state": str(state_file)}))
    sys.stdout.flush()
    deadline = time.time() + seconds
    try:
        while time.time() < deadline and not hits:
            srv.handle_request()
    finally:
        srv.server_close()
    print(json.dumps({"hits": len(hits), "local": bool(hits), "nonce": nonce}))
    sys.exit(0 if hits else 3)


def beacon_check(nonce: str, port: int) -> None:
    state_file = beacon_state_path(nonce, port)
    if not state_file.exists():
        print(json.dumps({"hits": 0, "local": False, "nonce": nonce, "note": f"no beacon state at {state_file}"}))
        sys.exit(3)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    hits = state.get("hits", [])
    ok = bool(hits) and state.get("nonce") == nonce
    print(json.dumps({"hits": len(hits), "local": ok, "nonce": state.get("nonce")}))
    sys.exit(0 if ok else 3)


# ---------------------------------------------------------------- roster
def read_connected(src):
    if not src:
        return []
    if src == "-":
        raw = sys.stdin.read()
    else:
        try:
            raw = Path(src).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise SystemExit(f"whichrome: no such file: {src}. Save the list_connected_browsers "
                             f"JSON array to a file first, or pipe it in with --connected -")
        except OSError as exc:
            raise SystemExit(f"whichrome: could not read {src}: {exc}")
    raw = raw.strip()
    if not raw:
        raise SystemExit(f"whichrome: {src} is empty. It should hold the JSON array from list_connected_browsers.")
    # Tolerate the tool result being pasted with prose around the JSON array.
    if not raw.startswith("["):
        m = re.search(r"\[\s*{.*?}\s*\]", raw, re.S)
        if not m:
            raise SystemExit("whichrome: could not find a JSON array of browsers in that input.")
        raw = m.group(0)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"whichrome: the browser list is not valid JSON ({exc}).")
    if not isinstance(parsed, list):
        raise SystemExit(f"whichrome: expected a JSON array of browsers, found {type(parsed).__name__}.")
    good = [e for e in parsed if isinstance(e, dict) and e.get("deviceId")]
    if len(good) != len(parsed):
        print(f"whichrome: ignored {len(parsed) - len(good)} entries with no deviceId", file=sys.stderr)
    return good


def locality(rec: dict, key: str):
    """(is_local, proven) - never claim a machine we did not prove."""
    proof = rec.get("localityProof")
    if not rec.get("device"):
        return None, False
    same = rec.get("device") == key
    return same, proof == "beacon"


def describe(rec: dict, dev_label, is_local_now) -> str:
    bits = []
    nick = rec.get("nickname")
    account = rec.get("account")
    bits.append(nick or "unidentified")
    if account:
        bits.append(account)
    where = dev_label or rec.get("deviceLabel")
    if where:
        bits.append(f"on {where}")
    if is_local_now is True:
        bits.append("THIS computer")
    elif is_local_now is False:
        bits.append("REMOTE - not this computer")
    elif is_local_now == "probably-here":
        bits.append("recorded here, not beacon-proved")
    elif is_local_now == "probably-remote":
        bits.append("recorded elsewhere, not beacon-proved")
    return " - ".join(bits)


def locality_label(rec: dict, key: str):
    same, proven = locality(rec, key)
    if same is None:
        return None
    if proven:
        return same
    return "probably-here" if same else "probably-remote"


def cmd_roster(args) -> None:
    data = load()
    key = ensure_device(data)
    here = data["devices"][key]
    connected = read_connected(args.connected)
    rows = []
    for entry in connected:
        did = entry.get("deviceId")
        rec = data["browsers"].get(did, {})
        rec_device = rec.get("device")
        # Locality: a recorded device key that matches this machine is the strongest signal;
        # the extension's own isLocal flag is advisory only (it has been wrong across machines).
        local_now = locality_label(rec, key)
        label = None
        if rec_device and rec_device in data["devices"]:
            label = data["devices"][rec_device].get("label")
        rows.append({
            "deviceId": did,
            "extensionName": entry.get("name"),
            "extensionIsLocal": entry.get("isLocal"),
            "nickname": rec.get("nickname"),
            "account": rec.get("account"),
            "chromeProfileDir": rec.get("chromeProfileDir"),
            "device": rec_device,
            "deviceLabel": label,
            "localityProof": rec.get("localityProof"),
            "knownLocalHere": local_now,
            "lastVerified": rec.get("lastVerified"),
            "isDefault": bool(rec.get("default")),
            "summary": describe(rec, label, local_now),
        })
    if args.json:
        print(json.dumps({
            "thisDevice": {"key": key, "label": here.get("label"), "hostname": here.get("hostname")},
            "browsers": rows,
            "unknownCount": sum(1 for r in rows if not r["nickname"]),
        }, indent=2))
        return
    print(f"This computer: {here.get('label')} ({here.get('hostname')})  key={key}")
    if not rows:
        if args.connected:
            print(f"{args.connected} parsed fine but listed no browsers: nothing is connected to the extension right now.")
        else:
            print("No --connected given. Run list_connected_browsers, save the JSON array, and pass it with --connected.")
        return
    width = max(len(r["deviceId"] or "") for r in rows)
    for r in rows:
        star = "*" if r["isDefault"] else " "
        print(f"{star} {(r['deviceId'] or ''):{width}}  {r['summary']}"
              + (f"  [ext: {r['extensionName']}]" if r["extensionName"] else ""))
    unknown = [r for r in rows if not r["nickname"]]
    if unknown:
        print(f"\n{len(unknown)} unidentified. Fingerprint each, then: whichrome record --id <id> --account <email> --nickname <name>")


BROADCAST_OPTION = "Open a confirmation screen in every connected Chrome extension and let me select the right one there."
MAX_OPTIONS = 4  # AskUserQuestion accepts 2-4 options.


def cmd_picker(args) -> None:
    """Emit AskUserQuestion-ready options: every browser, unavailable ones plainly marked."""
    data = load()
    key = ensure_device(data)
    save(data)
    connected = {e.get("deviceId"): e for e in read_connected(args.connected)}
    want = (args.want or "").strip().lower()

    universe = []
    for did in list(connected.keys()) + [d for d in data["browsers"] if d not in connected]:
        rec = data["browsers"].get(did, {})
        names = [rec.get("nickname", "")] + list(rec.get("aliases", []))
        is_connected = did in connected
        on_other_device = bool(rec.get("device")) and rec.get("device") != key
        other_label = data["devices"].get(rec.get("device", ""), {}).get("label") or "another computer"
        if not is_connected:
            status, why = "unavailable", "not connected to the extension right now"
        elif on_other_device and rec.get("localityProof") == "beacon":
            # Connected, but proved to live on a different machine: usable, yet nobody here will see it.
            status, why = "elsewhere", f"connected, but it runs on {other_label} - you would not see the window"
        else:
            status, why = "available", ""
        universe.append({
            "deviceId": did,
            "nickname": rec.get("nickname"),
            "account": rec.get("account"),
            "device": rec.get("device"),
            "deviceLabel": data["devices"].get(rec.get("device", ""), {}).get("label"),
            "status": status,
            "unavailableReason": why,
            "isDefault": bool(rec.get("default")),
            "wanted": bool(want) and want in [n.strip().lower() for n in names if n],
            "localProved": rec.get("localityProof") == "beacon" and rec.get("device") == key,
            "known": bool(rec.get("nickname")),
            "extensionName": connected.get(did, {}).get("name"),
        })

    order = {"available": 0, "elsewhere": 1, "unavailable": 2}
    universe.sort(key=lambda b: (
        order.get(b["status"], 3), not b["wanted"], not b["isDefault"],
        not b["localProved"], not b["known"], b["nickname"] or "~",
    ))

    def label_for(b):
        name = b["nickname"] or (b["extensionName"] and f"{b['extensionName']} (unidentified)") or "unidentified"
        bits = [name]
        if b["account"]:
            bits.append(b["account"])
        text = " - ".join(bits)
        if b["status"] == "unavailable":
            text += " [UNAVAILABLE]"
        elif b["status"] == "elsewhere":
            text += " [ON ANOTHER COMPUTER]"
        elif b["wanted"] or b["isDefault"]:
            text += " (recommended)"
        return text[:120]

    def desc_for(b):
        parts = [f"deviceId {b['deviceId'][:8]}"]
        if b["deviceLabel"]:
            parts.append("on " + b["deviceLabel"])
        if b["localProved"]:
            parts.append("proved to be on this computer")
        if b["status"] == "unavailable":
            parts.append("UNAVAILABLE: " + b["unavailableReason"] + " - picking it will not work until it reconnects")
        elif b["status"] == "elsewhere":
            parts.append("WARNING: " + b["unavailableReason"])
        elif not b["known"]:
            parts.append("not yet identified; I will fingerprint it before using it")
        return ". ".join(parts) + "."

    slots = MAX_OPTIONS - 1  # the broadcast option always takes the last slot
    if len(universe) > slots:
        shown, overflow = universe[:slots - 1], universe[slots - 1:]  # keep a whole slot for the overflow list
    else:
        shown, overflow = universe, []
    options = [{"label": label_for(b), "description": desc_for(b)} for b in shown]
    if overflow:
        names = ", ".join((b["nickname"] or b["extensionName"] or b["deviceId"][:8]) + {"available": "", "elsewhere": " [on another computer]", "unavailable": " [unavailable]"}.get(b["status"], "") for b in overflow)
        options.append({
            "label": f"Other browsers ({len(overflow)}) - say which",
            "description": f"Not shown above for lack of room: {names}. Answer with the name you want and I will select it.",
        })
    options.append({
        "label": BROADCAST_OPTION,
        "description": "Broadcasts a Connect prompt to every Chrome with the extension; click Connect in the one you want. Use this when nothing above is right.",
    })

    out = {
        "thisComputer": data["devices"][key].get("label"),
        "question": args.question or "Which Chrome should I use?",
        "header": "Browser",
        "multiSelect": False,
        "options": options,
        "all": universe,
        "availableCount": sum(1 for b in universe if b["status"] == "available"),
        "elsewhereCount": sum(1 for b in universe if b["status"] == "elsewhere"),
        "unavailableCount": sum(1 for b in universe if b["status"] == "unavailable"),
    }
    print(json.dumps(out, indent=2))


def cmd_resolve(args) -> None:
    data = load()
    key = device_key()
    want = args.name.strip().lower()
    matches = []
    for did, rec in data["browsers"].items():
        names = [rec.get("nickname", "")] + list(rec.get("aliases", []))
        if want in [n.strip().lower() for n in names if n]:
            matches.append((did, rec))
    if not matches:
        raise SystemExit(f"whichrome: no browser nicknamed {args.name!r}. Try: whichrome nicknames")
    if len(matches) > 1:
        # Never silently pick one of several: an ambiguous name is a question, not a default.
        # Only locality narrows the field. Preferring an exact nickname over an alias would
        # hide a genuine collision between two different browsers.
        local = [m for m in matches if m[1].get("device") == key]
        pool = local or matches
        if len(pool) > 1:
            lines = [f"  {d}  {describe(r, None, locality_label(r, key))}" for d, r in pool]
            raise SystemExit(f"whichrome: {args.name!r} is ambiguous across {len(pool)} browsers:\n"
                             + "\n".join(lines)
                             + "\nRename one (whichrome record --id <id> --nickname <new>) or use the deviceId.")
        matches = pool
    did, rec = matches[0]
    is_local = locality_label(rec, key)
    warn = "" if is_local is True else ("  (WARNING: not proved to be on this computer)" if is_local != "probably-here" else "")
    if args.quiet:
        print(did)
    else:
        print(f"{did}  {describe(rec, None, is_local)}{warn}")


def cmd_record(args) -> None:
    data = load()
    key = ensure_device(data)
    rec = data["browsers"].setdefault(args.id, {})
    if args.nickname:
        rec["nickname"] = args.nickname
    if args.account:
        rec["account"] = args.account
    if args.profile_dir:
        rec["chromeProfileDir"] = args.profile_dir
    if args.notes:
        rec["notes"] = args.notes
    if args.alias:
        rec.setdefault("aliases", [])
        for a in args.alias:
            if a not in rec["aliases"]:
                rec["aliases"].append(a)
    if args.default:
        for other in data["browsers"].values():
            other.pop("default", None)
        rec["default"] = True
    if args.local is not None:
        if args.local:
            rec["device"] = key
            rec["localityProof"] = args.proof or "beacon"
        else:
            rec["localityProof"] = "not-local"
            rec.pop("device", None)
    rec["lastVerified"] = today()
    # Enrich from this machine's Chrome profile map when the account matches.
    if rec.get("account") and not rec.get("chromeProfileDir"):
        for directory, account in data["devices"][key].get("chromeProfiles", {}).items():
            if account.lower() == rec["account"].lower():
                rec["chromeProfileDir"] = directory
                break
    save(data)
    print(json.dumps({args.id: rec}, indent=2))


def cmd_device(args) -> None:
    data = load()
    existing = data["devices"].get(device_key(), {}).get("label")
    label = None if (args.if_unset and existing) else args.label
    key = ensure_device(data, label)
    if args.scan:
        data["devices"][key]["chromeProfiles"] = scan_profiles()
    save(data)
    print(json.dumps({key: data["devices"][key]}, indent=2))


def cmd_scan(args) -> None:
    data = load()
    key = ensure_device(data)
    profiles = scan_profiles()
    data["devices"][key]["chromeProfiles"] = profiles
    save(data)
    print(json.dumps({key: profiles}, indent=2))


def cmd_forget(args) -> None:
    data = load()
    if data["browsers"].pop(args.id, None) is None:
        raise SystemExit(f"whichrome: {args.id} was not in the registry.")
    save(data)
    print(f"forgot {args.id}")


def cmd_nicknames(args) -> None:
    data = load()
    key = device_key()
    for did, rec in sorted(data["browsers"].items(), key=lambda kv: (not kv[1].get("default"), kv[1].get("nickname") or "")):
        label = data["devices"].get(rec.get("device", ""), {}).get("label")
        print(f"{rec.get('nickname') or '(unnamed)':16} {did}  {describe(rec, label, locality_label(rec, key))}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="whichrome", description="Know which Chrome you're driving.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("device", help="print/record this computer's identity")
    p.add_argument("--label", help="friendly name for this computer, e.g. 'Desk PC'")
    p.add_argument("--if-unset", dest="if_unset", action="store_true",
                   help="only apply --label when this computer has no label yet (installers use this)")
    p.add_argument("--scan", action="store_true", help="also scan Chrome profiles")
    p.set_defaults(func=cmd_device)

    p = sub.add_parser("scan-profiles", help="record this computer's Chrome profile -> account map")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("roster", help="merge connected browsers with the registry")
    p.add_argument("--connected", help="file with the list_connected_browsers JSON array, or '-' for stdin")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_roster)

    p = sub.add_parser("picker", help="emit AskUserQuestion options for every browser, unavailable ones marked")
    p.add_argument("--connected", help="file with the list_connected_browsers JSON array, or '-' for stdin")
    p.add_argument("--want", help="nickname the user asked for, so it sorts first and reads (recommended)")
    p.add_argument("--question", help="override the question text")
    p.set_defaults(func=cmd_picker)

    p = sub.add_parser("resolve", help="nickname -> deviceId")
    p.add_argument("name")
    p.add_argument("--quiet", action="store_true", help="print only the deviceId")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("record", help="save what you learned about a browser")
    p.add_argument("--id", required=True, help="deviceId from list_connected_browsers")
    p.add_argument("--nickname")
    p.add_argument("--account")
    p.add_argument("--profile-dir")
    p.add_argument("--alias", action="append")
    p.add_argument("--notes")
    p.add_argument("--default", action="store_true", help="mark as the default browser")
    p.add_argument("--local", dest="local", action="store_true", default=None, help="proved to be on this computer")
    p.add_argument("--not-local", dest="local", action="store_false", help="proved NOT to be on this computer")
    p.add_argument("--proof", help="how locality was proved (beacon|user)")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("forget", help="remove a browser record")
    p.add_argument("id")
    p.set_defaults(func=cmd_forget)

    p = sub.add_parser("beacon", help="locality proof over loopback")
    p.add_argument("action", choices=["start", "check"])
    p.add_argument("--port", type=int, default=8799)
    p.add_argument("--nonce", default="whichrome")
    p.add_argument("--seconds", type=int, default=45)
    p.set_defaults(func=lambda a: beacon_start(a.port, a.nonce, a.seconds) if a.action == "start" else beacon_check(a.nonce, a.port))

    p = sub.add_parser("nicknames", help="list known nicknames")
    p.set_defaults(func=cmd_nicknames)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

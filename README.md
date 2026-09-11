# Whichrome

**Know which Chrome you're driving.**

Claude's Chrome extension lists your connected browsers as `Browser 1`, `Browser 2`,
`Browser 3`. The names are positional, they shuffle between sessions, and renaming them in
Chrome does not stick. Nothing tells you which *computer* each one is on.

So Claude guesses. It opens a page on your work laptop while you're sitting at your desktop,
and you spend the next five minutes hunting for a window that isn't on your screen.

Whichrome fixes that with a registry Claude reads before it touches a browser.

```
This computer: Desk PC (DESKPC)
* 1ec7d06e-…  cyborg - you@example.com - on Desk PC - THIS computer
  ba237d7c-…  cyborg-2 - you@example.com - on Desk PC - recorded here, not beacon-proved
  9653c8f9-…  work - work@example.com - on Work laptop - REMOTE - not this computer
  09b0a7ec-…  unidentified
```

Now "use the cyborg" resolves to a deviceId instead of a scavenger hunt.

## Install

macOS / Linux / Git Bash:

```bash
curl -fsSL https://raw.githubusercontent.com/chilooby/whichrome/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/chilooby/whichrome/main/install.ps1 | iex
```

That clones the repo, installs the skill into `~/.claude/skills/whichrome/`, puts a
`whichrome` launcher in `~/.local/bin`, registers the computer you're on, and scans Chrome's
own `Local State` so every local profile directory is already mapped to its signed-in account.
Run it once per computer. No `whichrome` on PATH? Call
`python <repo>/bin/whichrome.py` instead; every example below works either way.

Then just use Claude normally. The skill fires before any browser action.

## What it actually does

**Remembers profiles by deviceId.** The only stable handle the extension exposes. Nicknames,
accounts, aliases and Chrome profile directories hang off it.

**Knows which computer each browser is on.** Every record is keyed to a device fingerprint
(hostname + machine UUID), so a browser registered on your desktop is flagged
`REMOTE - not this computer` when you're on your laptop.

**Proves locality instead of trusting a flag.** The extension's `isLocal` has reported `true`
for browsers on other machines. Whichrome serves a nonce on `127.0.0.1` and navigates the
candidate browser to it. Only a Chrome running on this machine can reach it:

```bash
whichrome beacon start --port 8799 --nonce probe-1 &
# ...navigate the browser to http://127.0.0.1:8799/probe-1...
whichrome beacon check --nonce probe-1 --port 8799   # exit 0 local, 3 not local, 4 port busy
```

Only a request carrying the nonce counts, each probe gets its own state file, and the port is
not shared, so a stray page or a second probe cannot forge a local verdict.

**Turns the required prompt into a useful one.** The extension makes Claude ask which browser
to use whenever several are connected. Whichrome supplies the labels, so instead of
"Browser 1 / Browser 2 / Browser 3" you get names, accounts, and which machine each is on,
with the likely one first.

**Syncs across devices and Claude surfaces.** The registry is one plain JSON file. It lives at
`~/.whichrome-registry.json` by default, deliberately outside the repo. Point
`WHICHROME_REGISTRY` at a synced folder or a private repo on each machine and every Claude
session on any of them knows your browsers.

## CLI

```bash
whichrome device --label "MacBook" --scan     # register this computer + scan Chrome profiles
whichrome roster --connected connected.json   # merge the extension's list with the registry
whichrome resolve cyborg --quiet              # nickname -> deviceId
whichrome record --id <deviceId> --nickname cyborg --account you@example.com --default --local
whichrome picker --connected connected.json --want cyborg   # ready-made AskUserQuestion options
whichrome nicknames                           # everything known
whichrome beacon start|check                  # locality proof
whichrome forget <deviceId>
```

`roster` accepts the `list_connected_browsers` JSON array from a file or stdin, and tolerates
prose pasted around it. `--json` emits machine-readable rows including `knownLocalHere`
(`true` proved local, `"probably-here"` recorded here but unproved, `"probably-remote"`
recorded elsewhere, `false` proved remote, `null` unknown). `picker` emits the
`AskUserQuestion` options directly, marking `[ON ANOTHER COMPUTER]` and `[UNAVAILABLE]`.

## Registry format

```jsonc
{
  "version": 1,
  "devices": {
    "DESKPC|00000000-…": {
      "label": "Desk PC",
      "hostname": "DESKPC",
      "os": "Windows",
      "lastSeen": "2026-09-11",
      "chromeProfiles": { "Profile 1": "you@example.com" }
    }
  },
  "browsers": {
    "ba237d7c-…": {
      "nickname": "cyborg",
      "account": "you@example.com",
      "chromeProfileDir": "Profile 1",
      "device": "DESKPC|00000000-…",
      "localityProof": "beacon",
      "aliases": ["research"],
      "default": true,
      "lastVerified": "2026-09-11",
      "notes": "The window holding the signed-in session."
    }
  }
}
```

It holds account addresses, machine labels and a machine id, never tokens or cookies. That is
still personal data, which is why the registry is not part of the repo and is gitignored: a
clone you publish contains `registry.example.json` and nothing about you. `--scan` reads only
the profile directory name and signed-in address from Chrome's `Local State`; it ignores
everything else in that file.

## Requirements

Python 3.9+, git, and Claude with the Chrome extension. No third-party packages.

## Gotchas worth knowing

- `accounts.google.com` is blocked for the extension, so Google sign-in and OAuth consent
  screens have to be clicked by a human. Whichrome's job is making sure that human is told
  *which window on which computer*.
- The extension often opens its tab group in a separate Chrome window that sits behind the
  others.
- One Chrome profile can connect twice and show up as two deviceIds with the same account, and
  only one of them holds the window with your live session. Nickname them apart and mark the
  live one `--default`; the fingerprint alone cannot tell them apart.
- Tab ids belong to a single browser; after switching, re-read the tab context.

## License

MIT

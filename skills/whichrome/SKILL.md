---
name: whichrome
description: Use BEFORE any Claude-in-Chrome browser action (navigate, computer, read_page, find, browser_batch, get_page_text) whenever a browser tool is about to be used. Identifies which connected Chrome profile is which, on which physical computer, so Claude never drives a browser on a machine the user is not sitting at. Also use when the user names a profile ("use the cyborg", "my work Chrome"), when list_connected_browsers shows more than one browser, or when a browser action fails with a tab or window that cannot be found.
---

# Whichrome

The Claude Chrome extension lists connected browsers as "Browser 1..N". Those names are
positional, they change between sessions, and renaming them in Chrome does not stick. A
deviceId is the only stable handle, and nothing in the extension reliably tells you which
*computer* a browser is on. Driving the wrong one opens pages on a machine nobody is watching.

Whichrome keeps a registry mapping each deviceId to a nickname, a Google account, a Chrome
profile directory, and the computer it lives on. Read it first, ask with real labels, act.

## The rule

Never call `select_browser` on a guess, and never fall back to "the first connected browser".
Either the registry identifies it, or you fingerprint it, or you ask.

## Running the CLI

If the installer ran, `whichrome` is on PATH. Otherwise call it by path:

```bash
python ${CLAUDE_PLUGIN_ROOT}/bin/whichrome.py nicknames
```

`${CLAUDE_PLUGIN_ROOT}` is the repo path. The installer substitutes the real path when it copies this
file into `~/.claude/skills/whichrome/`, so in the installed copy these commands are already
literal. If you are reading the repo copy and still see `${CLAUDE_PLUGIN_ROOT}`, replace it with the
path to this repo.

## Procedure

**1. Load the tools in ONE call.**

```
ToolSearch: select:mcp__claude-in-chrome__list_connected_browsers,mcp__claude-in-chrome__select_browser,mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__browser_batch,mcp__claude-in-chrome__find
```

**2. Build the roster.** Call `list_connected_browsers`, save the JSON array to a file, then:

```bash
whichrome roster --connected connected.json --json
```

Each row carries `knownLocalHere`: `true` beacon-proved on this machine, `"probably-here"`
recorded here but unproved, `"probably-remote"` recorded elsewhere, `false` proved elsewhere,
`null` unknown. Treat anything other than `true` as unproved.

**3. Ask the user, with labels that mean something.** Generate the options; do not hand-write
them:

```bash
whichrome picker --connected connected.json --want cyborg
```

That prints `options` ready to paste into `AskUserQuestion`: available browsers first, the
best match labelled `(recommended)`, browsers that are connected but proved to run on another
computer labelled `[ON ANOTHER COMPUTER]`, registry entries that are not connected labelled
`[UNAVAILABLE]` with the reason, and the required broadcast option last, worded exactly:

```
Open a confirmation screen in every connected Chrome extension and let me select the right one there.
```

`AskUserQuestion` accepts at most four options, so when more browsers exist the picker folds
the remainder into one `Other browsers (N) - say which` entry naming every one of them.
Nothing is silently hidden. If the user picks that entry they answer with a name; if they pick
the broadcast option call `switch_browser`; otherwise call `select_browser` with the chosen
deviceId.

**Ask unless all of these hold**, in which case go straight to it and say which you picked:

- exactly one browser is connected, or one matches the nickname the user just said, and
- its record is beacon-proved on this computer (`knownLocalHere` is `true`), and
- it was verified recently, and
- the user has not asked to be prompted every time.

**4. Prove locality before you show the user anything.** The `isLocal` flag has been observed
reading `true` for a browser whose window was not on this machine. That is a first-hand report,
not documented behaviour, so treat the flag as a hint and prove locality yourself: serve a nonce
on loopback and see whether the browser reaches it. Only a Chrome on this computer can.

Start it in the background. In bash:

```bash
whichrome beacon start --port 8799 --nonce probe-1 &
```

In PowerShell, `&` is not a backgrounding operator, so use:

```powershell
Start-Process -NoNewWindow whichrome -ArgumentList 'beacon','start','--port','8799','--nonce','probe-1'
```

Then `navigate` the selected browser to `http://127.0.0.1:8799/probe-1` and check:

```bash
whichrome beacon check --nonce probe-1 --port 8799   # exit 0 local, 3 not local, 4 port busy
whichrome record --id <deviceId> --local --proof beacon
```

Record `--not-local` when the beacon is not hit, and tell the user plainly that the browser
they picked is on another computer before asking them to look at it.

**5. Verify identity, then record it.**

```
tabs_context_mcp {createIfEmpty: true}
navigate -> https://myaccount.google.com/
get_page_text
```

The first two lines of that page are the profile name and the signed-in email. Prefer this
over `find` on google.com: it is plain text, needs no model call, and it still works when
`browser_batch` is timing out.

```bash
whichrome record --id <deviceId> --account <email> --nickname <name>
```

**When the fingerprint disagrees with the registry**, believe the fingerprint: the deviceId
was reassigned or the user switched profiles. Overwrite the record with `record --account ...`,
say out loud what changed, and do not reuse the stale nickname for this session.

**6. Resolve by nickname later.**

```bash
whichrome resolve cyborg --quiet   # -> deviceId, non-zero exit if ambiguous or unknown
whichrome nicknames
```

## Recording new computers

On a new machine, once (the installer does this for you):

```bash
whichrome device --label "MacBook" --scan
```

`--scan` reads Chrome's own `Local State` and records every local profile directory with its
signed-in account, so an account found by fingerprinting maps straight to a profile folder.

The registry lives at `~/.whichrome-registry.json`, outside the repo, because it holds account
addresses and machine ids. To share it across computers, point `WHICHROME_REGISTRY` at a
synced folder or a private repo on each machine.

## Hard-won gotchas

- One physical Chrome profile can connect twice and appear as two deviceIds with the same
  account, and only one holds the window with the user's live session. The account fingerprint
  cannot tell them apart, so record which is which (`cyborg` vs `cyborg-2`) and mark the live
  one `--default`. This is the most expensive mistake available: both look right, and the
  wrong one opens a window nobody is watching.
- `accounts.google.com` is blocked for the extension. Google account choosers and OAuth
  consent screens must be clicked by the user. Tell them the exact tab title (for example
  "Sign in - Google Accounts") and which profile it is in.
- The extension often opens its tab group in a *separate Chrome window* sitting behind the
  others. Say so when asking the user to find it.
- `switch_browser` broadcasts a Connect prompt to every extension and waits up to two minutes.
  It times out when nobody is watching that screen; prefer the registry plus fingerprint.
- Extension browser names are positional. The same deviceId was "Browser 3" one day and
  "Browser 2" the next. Only deviceIds are stable, and they survive reconnects.
- When `browser_batch` times out, fall back to single calls. A stalled batch can still have
  completed its earlier steps, so re-check state (for example `whichrome beacon check`) before
  assuming nothing happened.
- Tab ids belong to one browser. After `select_browser`, old tab ids are invalid: call
  `tabs_context_mcp {createIfEmpty: true}` again.

# Whichrome installer (Windows / PowerShell)
#   irm https://raw.githubusercontent.com/chilooby/whichrome/main/install.ps1 | iex
# or, from a clone:
#   .\install.ps1
[CmdletBinding()]
param(
  [string]$Repo = "https://github.com/chilooby/whichrome.git",
  [string]$InstallDir = "$HOME\.whichrome",
  [string]$SkillsDir = "$HOME\.claude\skills\whichrome",
  [switch]$NoClone
)

$ErrorActionPreference = "Stop"

function Info($m) { Write-Host "whichrome: $m" }

# 1. Get the source. Running from inside a clone uses it in place.
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if (Test-Path (Join-Path $scriptDir "bin\whichrome.py")) {
  $src = $scriptDir
  Info "using this clone: $src"
} elseif ($NoClone) {
  throw "No bin\whichrome.py next to install.ps1 and -NoClone was set."
} else {
  if (Test-Path (Join-Path $InstallDir ".git")) {
    Info "updating $InstallDir"
    git -C $InstallDir pull --ff-only | Out-Null
  } else {
    Info "cloning into $InstallDir"
    git clone --depth 1 $Repo $InstallDir | Out-Null
  }
  $src = $InstallDir
}

# 2. Find a Python that actually runs. Windows ships a `python3` Store stub that does nothing,
#    so test each candidate rather than trusting the first name that resolves.
$py = $null
foreach ($name in @("python", "py", "python3")) {
  $c = Get-Command $name -ErrorAction SilentlyContinue
  if (-not $c) { continue }
  try {
    & $c.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $c; break }
  } catch { }
}
if (-not $py) { throw "Whichrome needs Python 3.9+ on PATH (tried python, py, python3)." }
Info "python: $($py.Source)"

# 3. Install the skill with the real path baked in, so its commands are copy-pasteable.
New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null
$skill = Get-Content (Join-Path $src "SKILL.md") -Raw
$skill = $skill.Replace("<whichrome>", $src.Replace("\", "/"))
# Write UTF-8 without a BOM: 5.1's -Encoding utf8 adds one.
[System.IO.File]::WriteAllText((Join-Path $SkillsDir "SKILL.md"), $skill, (New-Object System.Text.UTF8Encoding($false)))
Info "skill installed -> $SkillsDir\SKILL.md"

# 4. Register this computer and its Chrome profiles.
& $py.Source (Join-Path $src "bin\whichrome.py") device --label $env:COMPUTERNAME --if-unset --scan | Out-Null
Info "registered this computer as '$env:COMPUTERNAME' and scanned its Chrome profiles"

# 5. A `whichrome.cmd` launcher so the documented commands work verbatim.
$binDir = Join-Path $HOME ".local/bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$entry = Join-Path $src "bin/whichrome.py"
$launcher = "@echo off`r`n`"$($py.Source)`" `"$entry`" %*`r`n"
[System.IO.File]::WriteAllText((Join-Path $binDir "whichrome.cmd"), $launcher)
Info "launcher installed -> $binDir\whichrome.cmd"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$binDir*") {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$binDir", "User")
  Info "added $binDir to your PATH (restart your shell to pick it up)"
}

# 6. Point the CLI at the registry. It is per-user data and deliberately not in the repo.
$registry = $env:WHICHROME_REGISTRY
if (-not $registry) { $registry = Join-Path $HOME ".whichrome-registry.json" }
[Environment]::SetEnvironmentVariable("WHICHROME_REGISTRY", $registry, "User")
Info "WHICHROME_REGISTRY -> $registry"

Write-Host ""
Info "done. In Claude Code, run:  /whichrome   (or just ask it to use a browser)"
Info "roster:  python `"$src\bin\whichrome.py`" nicknames"

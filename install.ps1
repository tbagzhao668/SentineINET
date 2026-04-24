$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

param(
  [string] $RepoUrl = $env:REPO_URL,
  [string] $Branch = $(if ($env:BRANCH) { $env:BRANCH } else { "main" }),
  [string] $TargetDir = $(if ($env:TARGET_DIR) { $env:TARGET_DIR } else { "AI_firewall_configer" }),
  [switch] $NoBuild
)

if ([string]::IsNullOrWhiteSpace($RepoUrl)) {
  $RepoUrl = "https://github.com/tbagzhao668/SentineINET.git"
}

function Assert-CommandExists {
  param([Parameter(Mandatory=$true)][string] $Name)
  $null = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $?) {
    throw "Missing dependency: $Name"
  }
}

Assert-CommandExists "git"
Assert-CommandExists "docker"

$composeOk = $false
try {
  docker compose version | Out-Null
  $composeOk = $true
} catch {
  $composeOk = $false
}

if (-not $composeOk) {
  throw "Docker Compose v2 is required (docker compose ...)."
}

if (Test-Path -LiteralPath (Join-Path $TargetDir ".git")) {
  Write-Host "Updating existing repo: $TargetDir"
  git -C $TargetDir fetch --all --prune | Out-Null
  git -C $TargetDir checkout $Branch | Out-Null
  git -C $TargetDir pull --ff-only | Out-Null
} elseif (Test-Path -LiteralPath $TargetDir) {
  throw "Target path exists but is not a git repo: $TargetDir"
} else {
  Write-Host "Cloning: $RepoUrl (branch: $Branch) -> $TargetDir"
  git clone --branch $Branch --depth 1 $RepoUrl $TargetDir | Out-Null
}

Push-Location $TargetDir
try {
  if ($NoBuild.IsPresent) {
    docker compose up -d
  } else {
    docker compose up -d --build
  }
} finally {
  Pop-Location
}

Write-Host ""
Write-Host "Done."
Write-Host "- Frontend: http://127.0.0.1:5175"
Write-Host "- Backend:  http://127.0.0.1:8000"

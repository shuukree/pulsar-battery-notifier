# One-shot: initialize git, create the GitHub repo, push, and tag the first release.
# Run from inside this folder in PowerShell:  .\push.ps1
#
# Requires GitHub CLI (https://cli.github.com). Check you're logged in first:
#   gh auth status
#
# Optional: change the repo name or visibility here.
$RepoName   = "pulsar-battery-notifier"
$Visibility = "--public"   # use "--private" for a private repo

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  Write-Error "GitHub CLI (gh) not found. Install it from https://cli.github.com, then run 'gh auth login'."
  exit 1
}

git init
git add .
git commit -m "Initial commit: Pulsar X2 Crazylight battery notifier"
git branch -M main

# Creates the repo on your account, adds it as 'origin', and pushes 'main'.
gh repo create $RepoName $Visibility --source=. --remote=origin --push

# Tag the first release -> triggers the GitHub Actions workflow to build the .exe.
git tag v1.0.0
git push origin v1.0.0

Write-Host ""
Write-Host "Done. Watch the build under the repo's Actions tab; the .exe lands on the v1.0.0 Release."

#requires -Version 5
$ErrorActionPreference = "Stop"

$Image = "ghcr.io/edison9733/receipt-bot:latest"
$Name  = "receiptbot"

function Test-Cmd($n) { $null -ne (Get-Command $n -ErrorAction SilentlyContinue) }

if (-not (Test-Cmd docker)) {
  Write-Host "Docker isn't installed. Install Docker Desktop, open it once, then re-run this:"
  Write-Host "  https://www.docker.com/products/docker-desktop/"
  exit 1
}

try { docker info *> $null } catch {
  Write-Host "Docker is installed but not running. Open Docker Desktop, wait for it to start, then re-run this."
  exit 1
}

$Token = (Read-Host "Paste your Telegram bot token (from @BotFather)").Trim()
if ([string]::IsNullOrWhiteSpace($Token)) { Write-Host "No token entered. Aborting."; exit 1 }

Write-Host "Pulling the latest bot image..."
docker pull $Image | Out-Null

Write-Host "Starting the bot..."
docker rm -f $Name 2>$null | Out-Null
docker run -d --name $Name --restart unless-stopped -p 8080:8080 -v receiptbot:/app/data -e TELEGRAM_TOKEN=$Token $Image | Out-Null

Write-Host ""
Write-Host "Bot is running."
Write-Host "In Telegram, message your bot and send:  /start  then  /connect"
Write-Host "After approving Google, send:  /setkey sk-...   then send a receipt photo."

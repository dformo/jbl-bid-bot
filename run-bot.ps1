<#
run-bot.ps1

Usage:
- Edit this file and replace the placeholder `YOUR_TOKEN_HERE`, OR
- Run interactively and paste your token when prompted:
    .\run-bot.ps1
- Pass token on the command line (less secure since it can be visible in process listings):
    .\run-bot.ps1 -Token "YOUR_TOKEN_HERE"

Security:
- Do NOT commit a real token into your repo. Keep this file out of version control if you place a token inside it.
#>

param(
    [string]$Token = "YOUR_TOKEN_HERE"
)

function Prompt-ForToken {
    $secure = Read-Host -Prompt "Enter DISCORD_TOKEN (input hidden)" -AsSecureString
    if ($secure.Length -eq 0) { return "" }
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

if ([string]::IsNullOrWhiteSpace($Token) -or $Token -eq 'YOUR_TOKEN_HERE') {
    Write-Host "No token provided on the command line or placeholder detected. Prompting for token..."
    $Token = Prompt-ForToken
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    Write-Error "No token provided. Exiting."
    exit 1
}

# Set env var for this PowerShell process (temp only)
$env:DISCORD_TOKEN = $Token

try {
    Write-Host "Starting jbl-bid-bot.py (DISCORD_TOKEN is set for this process only)..."
    & py .\jbl-bid-bot.py
}
finally {
    # Remove the env var from this session
    Remove-Item Env:DISCORD_TOKEN -ErrorAction SilentlyContinue
    Write-Host "Cleaned up DISCORD_TOKEN from session."
}
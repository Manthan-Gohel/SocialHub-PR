$ErrorActionPreference = "Continue"
$log = Join-Path $PSScriptRoot "daily.log"
$py  = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') run started ===" | Add-Content $log

& $py (Join-Path $PSScriptRoot "download_trending.py") *>> $log

if (Test-Path (Join-Path $PSScriptRoot "videos\_pending.json")) {
    & $py (Join-Path $PSScriptRoot "upload_youtube.py") *>> $log
} else {
    & $py (Join-Path $PSScriptRoot "upload_youtube.py") *>> $log
}

# Instagram cross-posting (needs INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD in .env)
& $py (Join-Path $PSScriptRoot "instagram_upload.py") *>> $log

"=== run finished ===" | Add-Content $log

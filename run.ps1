$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv/Scripts/python.exe')) { py -3 -m venv .venv; if ($LASTEXITCODE) { exit $LASTEXITCODE } }
& .venv/Scripts/python.exe -c 'import your_live_eye,requests,msgpack' 2>$null
if ($LASTEXITCODE) { & .venv/Scripts/python.exe -m pip install -e .; if ($LASTEXITCODE) { exit $LASTEXITCODE } }
& .venv/Scripts/python.exe -m your_live_eye @args
exit $LASTEXITCODE

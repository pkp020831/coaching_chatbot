$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "가상환경을 찾을 수 없습니다. 먼저 scripts\setup_windows.ps1을 실행해 주세요."
}

Set-Location $ProjectRoot
& $VenvPython serve_search_web.py
if ($LASTEXITCODE -ne 0) {
    throw "검색·답변 API가 오류로 종료되었습니다. 위 오류 내용을 확인해 주세요."
}

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$WebRoot = Join-Path $ProjectRoot "web"

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm을 찾을 수 없습니다. Node.js 22.13 이상을 설치해 주세요."
}
if (-not (Test-Path (Join-Path $WebRoot "node_modules"))) {
    throw "웹 패키지가 설치되지 않았습니다. 먼저 scripts\setup_windows.ps1을 실행해 주세요."
}

Set-Location $WebRoot
$NpmCommand = (Get-Command npm.cmd).Source
& $NpmCommand run dev:windows
if ($LASTEXITCODE -ne 0) {
    throw "웹 서버가 오류로 종료되었습니다. 위 오류 내용을 확인해 주세요."
}

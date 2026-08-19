$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[1/4] Python 가상환경을 준비합니다."
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m venv .venv
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m venv .venv
} else {
    throw "Python을 찾을 수 없습니다. Python 3.10 이상을 설치한 뒤 다시 실행해 주세요."
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "가상환경 Python을 만들지 못했습니다: $VenvPython"
}
& $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 이상이 필요합니다. 최신 Python을 설치한 뒤 .venv 폴더를 지우고 다시 실행해 주세요."
}

Write-Host "[2/4] Python 패키지를 설치합니다."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip 업그레이드에 실패했습니다. 인터넷 연결을 확인해 주세요."
}
& $VenvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Python 패키지 설치에 실패했습니다. 위 오류 내용을 확인해 주세요."
}

Write-Host "[3/4] 환경 설정 파일을 준비합니다."
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env 파일을 만들었습니다. 이 파일에 GEMINI_API_KEY를 입력해 주세요."
} else {
    Write-Host "기존 .env 파일을 그대로 사용합니다."
}

Write-Host "[4/4] 웹 패키지를 설치합니다."
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm을 찾을 수 없습니다. Node.js 22.13 이상을 설치한 뒤 다시 실행해 주세요."
}
$NpmCommand = (Get-Command npm.cmd).Source

Push-Location (Join-Path $ProjectRoot "web")
try {
    & $NpmCommand install
    if ($LASTEXITCODE -ne 0) {
        throw "웹 패키지 설치에 실패했습니다. 위 오류 내용을 확인해 주세요."
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "설치가 완료되었습니다."
Write-Host "1) .env 파일에 GEMINI_API_KEY를 입력하세요."
Write-Host "2) 첫 번째 PowerShell에서 아래 명령을 실행하세요."
Write-Host "   powershell -ExecutionPolicy Bypass -File .\scripts\start_api_windows.ps1"
Write-Host "3) 두 번째 PowerShell에서 아래 명령을 실행하세요."
Write-Host "   powershell -ExecutionPolicy Bypass -File .\scripts\start_web_windows.ps1"

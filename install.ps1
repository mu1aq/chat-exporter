# Install dependencies into a local .venv (PowerShell, any OS).
# After this finishes, run the tool with:  .venv\Scripts\python chat2file.py <share-url>
$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (Get-Command python3 -ErrorAction SilentlyContinue) {
    $Bootstrap = "python3"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Bootstrap = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Bootstrap = "py"
} else {
    Write-Error "Python was not found. Install Python 3.10 or newer."
    exit 127
}

$WindowsVenv = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$PosixVenv = Join-Path $ProjectDir ".venv/bin/python"
if (Test-Path -LiteralPath $WindowsVenv) {
    $VenvPy = $WindowsVenv
} elseif (Test-Path -LiteralPath $PosixVenv) {
    $VenvPy = $PosixVenv
} else {
    & $Bootstrap -m venv (Join-Path $ProjectDir ".venv")
    $VenvPy = if (Test-Path -LiteralPath $WindowsVenv) { $WindowsVenv } else { $PosixVenv }
}

& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -e "$ProjectDir[browser]"
& $VenvPy -m playwright install chromium

Write-Host "Done. Run:  $VenvPy $(Join-Path $ProjectDir 'chat2file.py') <share-url>"
exit $LASTEXITCODE

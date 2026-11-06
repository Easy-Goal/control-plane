# Instala o control plane no Windows, sem administrador. Linux, macOS, WSL e outros Unix: install.sh.
#   powershell -ExecutionPolicy Bypass -File install.ps1             usa o pacote desta pasta ou, em um clone, a própria pasta
#   powershell -ExecutionPolicy Bypass -File install.ps1 <pacote>    usa esse pacote, com o SHA256SUMS ao lado
# Precisa só de Python 3.9 ou mais novo. Nada é baixado nem instalado além do próprio programa.
param([string]$Package = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Python {
  $check = 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'
  foreach ($candidate in @(@('py', '-3'), @('python'), @('python3'))) {
    $exe = $candidate[0]
    $found = Get-Command $exe -ErrorAction SilentlyContinue
    # O atalho da Microsoft Store responde pelo nome python, mas não é um Python: ele só abre a loja.
    if (-not $found -or $found.Source -like '*\WindowsApps\*') { continue }
    $prefix = @($candidate | Select-Object -Skip 1)
    & $exe @prefix -c $check 2>$null
    if ($LASTEXITCODE -eq 0) { return ,$candidate }
  }
  return $null
}

$python = Find-Python
if (-not $python) {
  Write-Output 'Falta o Python 3.9 ou mais novo.'
  Write-Output '  Como resolver: winget install Python.Python.3.12'
  Write-Output 'Depois, abra um terminal novo e rode este comando de novo.'
  exit 1
}
$exe = $python[0]
$prefix = @($python | Select-Object -Skip 1)

if (-not $Package) {
  $found = Get-ChildItem -Path $here -Filter 'control-plane-*.tar.gz' -ErrorAction SilentlyContinue | Select-Object -Last 1
  if ($found) { $Package = $found.FullName }
}

if ($Package) {
  $script = Join-Path $here 'install.py'
  if (-not (Test-Path $script)) { Write-Output 'Falta o install.py ao lado do install.ps1. Baixe todos os arquivos do release.'; exit 1 }
  & $exe @prefix -I -B $script --package $Package
  exit $LASTEXITCODE
}
$script = Join-Path $here 'scripts\cp_install.py'
if (Test-Path $script) {
  & $exe @prefix -I -B $script --from-dir $here
  exit $LASTEXITCODE
}
Write-Output 'Não encontrei o pacote control-plane-<versão>.tar.gz nesta pasta.'
exit 1

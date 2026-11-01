# SPDX-License-Identifier: GPL-2.0-or-later
<#
.SYNOPSIS
    Certifica una celda de la matriz GeoDuck (instalación QGIS + método de instalación) en Windows 11 x64.

.DESCRIPTION
    Procedimiento de docs/certification/windows.md, paso 4. El script:
      1. Localiza el Python de la instalación de QGIS indicada (nunca un Python externo).
      2. Registra los hechos del entorno (QGIS, Qt, Python, NumPy).
      3. Instala duckdb y pyarrow con el método elegido, SIN dependencias (--no-deps) para no tocar
         la NumPy de QGIS:
           M1  dentro del Python de QGIS (requiere administrador)
           M2  en una carpeta propia (-DepsDir), sin modificar QGIS
           M3  en el site de usuario (pip --user)
      4. Ejecuta tools\verify_env.py y, opcionalmente, las suites de pytest con el Python de QGIS.
      5. Escribe los resultados y un SHA256SUMS.txt en -OutDir.

    No ejecuta nada sin que usted lo invoque, no instala la extensión spatial salvo con -InstallSpatial
    y no desinstala QGIS. Al final imprime los comandos para revertir la instalación.

.EXAMPLE
    .\Invoke-GeoDuckCertification.ps1 -QgisRoot "C:\Program Files\QGIS 3.44.15" -Method M2 `
        -Constraints ..\..\constraints\win-qgis-3.44-py312.txt -RunTestSuites
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$QgisRoot,
    [ValidateSet('M1', 'M2', 'M3')][string]$Method = 'M2',
    [Parameter(Mandatory = $true)][string]$Constraints,
    [string]$OutDir = (Join-Path (Get-Location) 'certification-results'),
    [string]$DepsDir = '',
    [switch]$InstallSpatial,
    [switch]$RunTestSuites
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Constraints = (Resolve-Path $Constraints).Path
if (-not (Test-Path $QgisRoot)) { throw "No existe la instalación de QGIS: $QgisRoot" }

# 1. Lanzador del Python de QGIS (python-qgis.bat o python-qgis-ltr.bat configuran el entorno de QGIS)
$launcher = Get-ChildItem -Path (Join-Path $QgisRoot 'bin') -Filter 'python-qgis*.bat' -ErrorAction SilentlyContinue |
    Sort-Object Name | Select-Object -First 1
if (-not $launcher) {
    throw "No se encontró bin\python-qgis*.bat en $QgisRoot. Indique la carpeta raíz de la instalación MSI/OSGeo4W."
}
function Invoke-QgisPython {
    # Recibe los argumentos como un único arreglo: así «-m» llega a Python y no a PowerShell.
    param([Parameter(Mandatory = $true)][string[]]$PyArgs)
    # La salida va a la consola; la función devuelve solo el código de salida.
    & $launcher.FullName @PyArgs | Out-Host
    return $LASTEXITCODE
}

$cell = 'win-' + ((Split-Path $QgisRoot -Leaf) -replace '[^A-Za-z0-9.]+', '-').ToLower() + "-$Method"
$cellOut = Join-Path $OutDir $cell
New-Item -ItemType Directory -Force -Path $cellOut | Out-Null
Start-Transcript -Path (Join-Path $cellOut 'transcript.txt') -Force | Out-Null

try {
    Write-Host "== GeoDuck · certificación de la celda $cell"
    Write-Host "   Lanzador: $($launcher.FullName)"

    # 2. Hechos del entorno
    $factsPy = @'
import json, platform, struct, sys
facts = {"python": sys.version, "executable": sys.executable, "bits": struct.calcsize("P") * 8,
         "platform": platform.platform()}
try:
    import numpy; facts["numpy"] = numpy.__version__; facts["numpy_file"] = numpy.__file__
except Exception as exc:
    facts["numpy"] = f"no disponible: {exc}"
try:
    from qgis.core import Qgis; from qgis.PyQt.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
    facts.update(qgis=Qgis.version(), qt=QT_VERSION_STR, pyqt=PYQT_VERSION_STR)
except Exception as exc:
    facts["qgis"] = f"no importable: {exc}"
print(json.dumps(facts, ensure_ascii=False))
'@
    $factsFile = Join-Path $cellOut 'facts.json'
    $factsScript = Join-Path $env:TEMP 'geoduck_facts.py'
    Set-Content -Path $factsScript -Value $factsPy -Encoding UTF8
    $factsJson = & $launcher.FullName $factsScript
    Set-Content -Path $factsFile -Value $factsJson -Encoding UTF8
    Write-Host "   Hechos: $factsJson"

    # 3. Instalación según el método (siempre --no-deps: no se toca la NumPy de QGIS)
    $pipCommon = @('-m', 'pip', 'install', '--no-input', '--disable-pip-version-check', '--no-deps',
        '--only-binary=:all:', '-r', $Constraints)
    $verifyExtra = @()
    $undo = ''
    switch ($Method) {
        'M1' {
            $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
                ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            if (-not $isAdmin) { throw 'M1 instala dentro de la carpeta de QGIS: ejecute PowerShell como administrador.' }
            $rc = Invoke-QgisPython -PyArgs $pipCommon
            $undo = "& `"$($launcher.FullName)`" -m pip uninstall -y duckdb pyarrow"
        }
        'M2' {
            if (-not $DepsDir) { $DepsDir = Join-Path $env:LOCALAPPDATA "GeoDuck\deps\$cell" }
            New-Item -ItemType Directory -Force -Path $DepsDir | Out-Null
            $rc = Invoke-QgisPython -PyArgs ($pipCommon + @('--target', $DepsDir, '--upgrade'))
            $verifyExtra = @('--deps-dir', $DepsDir)
            $undo = "Remove-Item -Recurse -Force `"$DepsDir`""
        }
        'M3' {
            $rc = Invoke-QgisPython -PyArgs ($pipCommon + @('--user'))
            $undo = "& `"$($launcher.FullName)`" -m pip uninstall -y duckdb pyarrow"
        }
    }
    if ($rc -ne 0) { throw "pip terminó con código $rc (método $Method)" }

    # 4. Verificador y suites de pruebas
    $verifyArgs = @((Join-Path $Repo 'tools\verify_env.py'), '--out', $cellOut) + $verifyExtra
    if ($InstallSpatial) { $verifyArgs += '--install-spatial' }
    $verifyRc = Invoke-QgisPython -PyArgs $verifyArgs

    $pytestRc = $null
    if ($RunTestSuites) {
        $testDeps = Join-Path $cellOut '_testdeps'
        $rc = Invoke-QgisPython -PyArgs @('-m', 'pip', 'install', '--no-input', '--disable-pip-version-check',
            '--target', $testDeps, 'pytest>=8')
        if ($rc -ne 0) { throw 'No se pudo preparar pytest en una carpeta aislada' }
        $paths = @($testDeps)
        if ($Method -eq 'M2') { $paths = @($DepsDir) + $paths }
        $env:PYTHONPATH = ($paths -join [IO.Path]::PathSeparator)
        Push-Location $Repo
        try {
            $pytestRc = Invoke-QgisPython -PyArgs @('-m', 'pytest', 'tests/unit', 'tests/architecture',
                'tests/engine', 'tests/qgis', '-q', '-p', 'no:cacheprovider',
                "--junitxml=$(Join-Path $cellOut 'pytest.xml')")
        } finally {
            Pop-Location
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
    }

    # 5. Integridad de los resultados
    Get-ChildItem -Path $cellOut -File -Recurse | Where-Object { $_.FullName -notlike '*\_testdeps\*' } |
        Get-FileHash -Algorithm SHA256 |
        ForEach-Object { "{0}  {1}" -f $_.Hash.ToLower(), $_.Path.Substring($cellOut.Length + 1) } |
        Set-Content -Path (Join-Path $cellOut 'SHA256SUMS.txt') -Encoding UTF8

    Write-Host ''
    Write-Host "== Resultado verify_env: $(if ($verifyRc -eq 0) { 'APTO' } else { 'NO APTO' }) (código $verifyRc)"
    if ($null -ne $pytestRc) { Write-Host "== Resultado pytest: código $pytestRc" }
    Write-Host "== Resultados en: $cellOut"
    Write-Host "== Para revertir la instalación de dependencias:  $undo"
    if ($InstallSpatial) {
        Write-Host '== Para eliminar spatial: borre la carpeta indicada en report.json (extension_directory) o %USERPROFILE%\.duckdb\extensions'
    }
    exit ([int]($verifyRc -ne 0) + [int](($null -ne $pytestRc) -and ($pytestRc -ne 0)))
}
finally {
    Stop-Transcript | Out-Null
}

# cfe-build v1.1 — Build a compiled extension (.cfe) from XML sources via a throwaway infobase
# Unlike a deploy against a shared/persistent infobase, this always (re)creates a fresh
# local infobase, optionally loads a compiled base configuration (-BaseCfFile) into it,
# loads the extension XML source as an extension, dumps the compiled .cfe, and leaves the
# throwaway infobase behind for inspection (rerun to get a clean one).
#
# -BaseCfFile is required whenever the extension borrows objects from the base
# configuration (ObjectBelonging=Adopted) — verified empirically: loading such an
# extension into a truly empty infobase (no base config at all) fails at the platform
# level with dozens/hundreds of "Не найден объект ..." errors and a non-zero exit code,
# because the extension's adopted-object references cannot resolve. A standalone
# extension with no adopted objects can omit -BaseCfFile.
<#
.SYNOPSIS
    Сборка скомпилированного расширения (.cfe) из XML-исходников через временную ИБ

.DESCRIPTION
    Создаёт (пересоздаёт) локальную временную информационную базу, при необходимости
    загружает в неё скомпилированную основную конфигурацию (-BaseCfFile), загружает
    XML-исходники расширения как расширение, выгружает скомпилированный .cfe.

.PARAMETER ExtensionPath
    Путь к каталогу с XML-исходниками расширения (содержит Configuration.xml)

.PARAMETER V8Path
    Путь к каталогу bin платформы или к 1cv8.exe

.PARAMETER BasePath
    Каталог временной информационной базы, пересоздаётся при каждом запуске (по умолчанию base/empty)

.PARAMETER BaseCfFile
    Скомпилированная основная конфигурация (.cf) для загрузки перед расширением —
    обязательна, если расширение содержит заимствованные (Adopted) объекты

.PARAMETER OutputFile
    Путь к выходному .cfe (по умолчанию build/<ExtensionName>.cfe)

.PARAMETER ExtensionName
    Имя расширения для -Extension (по умолчанию читается из Configuration.xml <Name>)

.PARAMETER UserName
    Имя пользователя 1С для временной информационной базы

.PARAMETER Password
    Пароль пользователя

.EXAMPLE
    .\cfe-build.ps1 -ExtensionPath "src\ext\МоеРасширение" -BaseCfFile "base\actual.cf" -OutputFile "build\МоеРасширение.cfe"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [Alias('Path')]
    [string]$ExtensionPath,

    [Parameter(Mandatory=$false)]
    [string]$V8Path,

    [Parameter(Mandatory=$false)]
    [string]$BasePath = (Join-Path "base" "empty"),

    [Parameter(Mandatory=$false)]
    [string]$BaseCfFile,

    [Parameter(Mandatory=$false)]
    [string]$OutputFile,

    [Parameter(Mandatory=$false)]
    [string]$ExtensionName,

    [Parameter(Mandatory=$false)]
    [string]$UserName,

    [Parameter(Mandatory=$false)]
    [string]$Password
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not (Test-Path $ExtensionPath -PathType Container)) {
    Write-Host "Error: extension path not found: $ExtensionPath" -ForegroundColor Red
    exit 1
}

if ($BaseCfFile -and -not (Test-Path $BaseCfFile -PathType Leaf)) {
    Write-Host "Error: base .cf file not found: $BaseCfFile" -ForegroundColor Red
    exit 1
}

# --- Resolve V8Path ---
# -V8Path is normally supplied explicitly by the calling agent, populated from
# .dev.env's PLATFORM_PATH (see AGENTS.md / dev-standards-core.md §1). The
# scan below is only a fallback for when it isn't passed.
if (-not $V8Path) {
    $found = Get-ChildItem @("C:\Program Files\1cv8\*\bin\1cv8.exe", "C:\Program Files (x86)\1cv8\*\bin\1cv8.exe") -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]"0.0" } } -Descending |
        Select-Object -First 1
    if ($found) {
        $V8Path = $found.FullName
        Write-Host "Auto-selected platform $($found.Directory.Parent.Name): $V8Path" -ForegroundColor Yellow
    } else {
        Write-Host "Error: 1C executable not found. Specify -V8Path" -ForegroundColor Red
        exit 1
    }
}
if (Test-Path $V8Path -PathType Container) {
    $V8Path = Join-Path $V8Path "1cv8.exe"
}
if (-not (Test-Path $V8Path)) {
    Write-Host "Error: 1C executable not found at $V8Path" -ForegroundColor Red
    exit 1
}

# --- Read extension name from Configuration.xml <Name> (usually differs from the source
#     directory name, e.g. dir base_МоеРасширение, name МоеРасширение) ---
if (-not $ExtensionName) {
    $cfgFile = Join-Path $ExtensionPath "Configuration.xml"
    if (-not (Test-Path $cfgFile)) {
        Write-Host "Error: Configuration.xml not found in extension path: $cfgFile" -ForegroundColor Red
        exit 1
    }
    [xml]$cfgDoc = Get-Content -Path $cfgFile -Encoding UTF8
    $ns = New-Object System.Xml.XmlNamespaceManager($cfgDoc.NameTable)
    $ns.AddNamespace("md", "http://v8.1c.ru/8.3/MDClasses")
    $nameNode = $cfgDoc.SelectSingleNode("//md:Configuration/md:Properties/md:Name", $ns)
    if (-not $nameNode -or -not $nameNode.InnerText) {
        Write-Host "Error: <Name> not found in $cfgFile" -ForegroundColor Red
        exit 1
    }
    $ExtensionName = $nameNode.InnerText.Trim()
}
Write-Host "Extension name: $ExtensionName"

if (-not $OutputFile) {
    $OutputFile = Join-Path "build" "$ExtensionName.cfe"
}
$outDir = Split-Path $OutputFile -Parent
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$scriptsDir = Split-Path $PSScriptRoot -Parent | Split-Path -Parent
$dbOpsDir = Join-Path (Join-Path $scriptsDir "1c-db-ops") "scripts"
$dbCreate = Join-Path $dbOpsDir "db-create.ps1"
$dbLoadCf = Join-Path $dbOpsDir "db-load-cf.ps1"
$dbLoadXml = Join-Path $dbOpsDir "db-load-xml.ps1"
$dbUpdate = Join-Path $dbOpsDir "db-update.ps1"
$dbDumpCf = Join-Path $dbOpsDir "db-dump-cf.ps1"

function Invoke-Step {
    param([string]$ScriptPath, [string[]]$StepArgs, [string]$Description)
    Write-Host ""
    Write-Host "--- $Description ---"
    Write-Host "Running: powershell.exe -NoProfile -File `"$ScriptPath`" $($StepArgs -join ' ')"
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList (@("-NoProfile", "-File", "`"$ScriptPath`"") + $StepArgs) -NoNewWindow -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Write-Host "Error: $Description failed (code: $($proc.ExitCode))" -ForegroundColor Red
        exit $proc.ExitCode
    }
}

$totalSteps = if ($BaseCfFile) { 5 } else { 3 }
$stepN = 1

# --- Step: recreate the throwaway empty infobase ---
$basePathFull = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $BasePath))
if (Test-Path $basePathFull) {
    Remove-Item -Path $basePathFull -Recurse -Force
}
New-Item -ItemType Directory -Path $basePathFull -Force | Out-Null

Invoke-Step -ScriptPath $dbCreate -StepArgs @("-V8Path", "`"$V8Path`"", "-InfoBasePath", "`"$basePathFull`"") `
    -Description "Step $stepN/$totalSteps`: create empty infobase"
$stepN++

# --- Step (optional): load the base configuration the extension borrows objects from ---
if ($BaseCfFile) {
    $baseCfFull = (Resolve-Path $BaseCfFile).Path
    $loadCfArgs = @("-V8Path", "`"$V8Path`"", "-InfoBasePath", "`"$basePathFull`"", "-InputFile", "`"$baseCfFull`"")
    if ($UserName) { $loadCfArgs += @("-UserName", "`"$UserName`"") }
    if ($Password) { $loadCfArgs += @("-Password", "`"$Password`"") }
    Invoke-Step -ScriptPath $dbLoadCf -StepArgs $loadCfArgs `
        -Description "Step $stepN/$totalSteps`: load base configuration ($BaseCfFile)"
    $stepN++

    $updateArgs = @("-V8Path", "`"$V8Path`"", "-InfoBasePath", "`"$basePathFull`"")
    if ($UserName) { $updateArgs += @("-UserName", "`"$UserName`"") }
    if ($Password) { $updateArgs += @("-Password", "`"$Password`"") }
    Invoke-Step -ScriptPath $dbUpdate -StepArgs $updateArgs `
        -Description "Step $stepN/$totalSteps`: apply base configuration to database"
    $stepN++
}

# --- Step: load the extension XML source as an extension ---
$loadArgs = @(
    "-V8Path", "`"$V8Path`"",
    "-InfoBasePath", "`"$basePathFull`"",
    "-ConfigDir", "`"$ExtensionPath`"",
    "-Mode", "Full",
    "-Extension", "`"$ExtensionName`"",
    "-UpdateDB"
)
if ($UserName) { $loadArgs += @("-UserName", "`"$UserName`"") }
if ($Password) { $loadArgs += @("-Password", "`"$Password`"") }
Invoke-Step -ScriptPath $dbLoadXml -StepArgs $loadArgs `
    -Description "Step $stepN/$totalSteps`: load extension configuration"
$stepN++

# --- Step: dump the compiled extension to .cfe ---
$dumpArgs = @(
    "-V8Path", "`"$V8Path`"",
    "-InfoBasePath", "`"$basePathFull`"",
    "-Extension", "`"$ExtensionName`"",
    "-OutputFile", "`"$OutputFile`""
)
if ($UserName) { $dumpArgs += @("-UserName", "`"$UserName`"") }
if ($Password) { $dumpArgs += @("-Password", "`"$Password`"") }
Invoke-Step -ScriptPath $dbDumpCf -StepArgs $dumpArgs `
    -Description "Step $stepN/$totalSteps`: dump compiled extension"

Write-Host ""
Write-Host "Build completed successfully: $OutputFile" -ForegroundColor Green

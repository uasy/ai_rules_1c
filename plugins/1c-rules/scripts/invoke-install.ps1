#Requires -Version 5.1
<#
.SYNOPSIS
    Marketplace wrapper around install.ps1.

.DESCRIPTION
    Host plugins (Cursor, Claude Code, OpenCode, Kilo Code) call this script
    instead of copying content/ themselves. Rules stay adapted per host
    because the real installer still runs.

    Actions:
      ensure  If this looks like a 1C project: init when there is no
              manifest, add the host tool when the manifest exists but
              lacks it, otherwise no-op. Never auto-updates.
      init    Always run install.ps1 init for the given tool.
      update  Always run install.ps1 update.
      doctor  Always run install.ps1 doctor.

    -DryRun prints one JSON object and does not call install.ps1.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('ensure', 'init', 'update', 'doctor')]
    [string]$Action = 'ensure',

    [ValidateSet('auto', 'cursor', 'claude-code', 'codex', 'opencode', 'kilocode')]
    [string]$Tool = 'auto',

    [string]$ProjectRoot,
    [string]$Source,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$script:DefaultSourceUrl = 'https://github.com/comol/ai_rules_1c.git'

function Get-NormalizedPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Test-SamePath {
    param([string]$Left, [string]$Right)
    if (-not $Left -or -not $Right) { return $false }
    return ((Get-NormalizedPath $Left).ToLowerInvariant() -eq (Get-NormalizedPath $Right).ToLowerInvariant())
}

function Get-HomeDirectory {
    if ($env:USERPROFILE) { return $env:USERPROFILE }
    if ($env:HOME) { return $env:HOME }
    return [Environment]::GetFolderPath('UserProfile')
}

function Test-ForbiddenProjectRoot {
    param([string]$Root)
    $resolved = Get-NormalizedPath $Root
    if (-not $resolved) { return $true }

    $userHome = Get-HomeDirectory
    $exact = New-Object System.Collections.Generic.List[string]
    foreach ($item in @(
            $userHome,
            (Join-Path $userHome 'Documents'),
            (Join-Path $userHome 'Desktop'),
            (Join-Path $userHome 'Downloads'),
            $env:TEMP,
            $env:TMP,
            ([System.IO.Path]::GetTempPath())
        )) {
        if ($item) { [void]$exact.Add((Get-NormalizedPath $item)) }
    }

    $cliLeaves = @(
        '.cursor', '.claude', '.codex', '.opencode', '.kilo', '.kilocode',
        '.kimi-code', '.kimi', '.qwen', '.commandcode', '.cline', '.pi',
        '.agents'
    )
    foreach ($leaf in $cliLeaves) {
        if ($userHome) { [void]$exact.Add((Get-NormalizedPath (Join-Path $userHome $leaf))) }
    }
    if ($userHome) {
        [void]$exact.Add((Get-NormalizedPath (Join-Path (Join-Path $userHome '.config') 'kilo')))
        [void]$exact.Add((Get-NormalizedPath (Join-Path (Join-Path $userHome '.config') 'opencode')))
        [void]$exact.Add((Get-NormalizedPath (Join-Path (Join-Path $userHome '.config') 'claude')))
    }
    if ($env:APPDATA) {
        foreach ($leaf in @('kilo', 'Kilo', 'Cursor', 'Claude', 'opencode')) {
            [void]$exact.Add((Get-NormalizedPath (Join-Path $env:APPDATA $leaf)))
        }
    }

    foreach ($item in $exact) {
        if ($item -and (Test-SamePath $resolved $item)) { return $true }
    }

    $leafName = Split-Path -Leaf $resolved
    if ($cliLeaves -contains $leafName.ToLowerInvariant()) {
        $parent = Split-Path -Parent $resolved
        if ($userHome -and (Test-SamePath $parent $userHome)) { return $true }
        if ($userHome -and (Test-SamePath $parent (Join-Path $userHome '.config'))) { return $true }
    }

    $kiloMarker = Join-Path $resolved 'kilo.jsonc'
    $pkg = Join-Path $resolved 'package.json'
    if ((Test-Path -LiteralPath $kiloMarker) -and (Test-Path -LiteralPath $pkg)) {
        $pkgText = Get-Content -LiteralPath $pkg -Raw -ErrorAction SilentlyContinue
        if ($pkgText -and ($pkgText -match '@kilocode/plugin|@openai/codex|@anthropic-ai/claude')) {
            return $true
        }
    }

    return $false
}

function Test-OneCProjectRoot {
    param([string]$Root)
    $markers = @(
        (Join-Path $Root 'Configuration.xml'),
        (Join-Path $Root 'ConfigurationExtension.xml'),
        (Join-Path $Root 'cf\Configuration.xml'),
        (Join-Path $Root 'src\Configuration.xml'),
        (Join-Path $Root 'src\cf\Configuration.xml')
    )
    foreach ($path in $markers) {
        if (Test-Path -LiteralPath $path) { return $true }
    }

    $devEnv = Join-Path $Root '.dev.env'
    if (Test-Path -LiteralPath $devEnv) {
        $text = Get-Content -LiteralPath $devEnv -Raw -ErrorAction SilentlyContinue
        if ($text -and ($text -match '(?m)^(PLATFORM_VERSION|PLATFORM_PATH|INFOBASE_PATH|PREFIX)=')) {
            return $true
        }
    }

    return $false
}

function Get-ManifestTools {
    param([string]$Root)
    $manifestPath = Join-Path $Root '.ai-rules.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { return $null }
    $raw = Get-Content -LiteralPath $manifestPath -Raw -ErrorAction SilentlyContinue
    if (-not $raw) { return @() }
    $obj = $raw | ConvertFrom-Json
    $tools = @()
    if ($obj.tools) {
        foreach ($item in @($obj.tools)) {
            if ($item) { $tools += [string]$item }
        }
    }
    return $tools
}

function Test-SourceTree {
    param([string]$Root)
    if (-not $Root) { return $false }
    return (
        (Test-Path -LiteralPath (Join-Path $Root 'install.ps1')) -and
        (Test-Path -LiteralPath (Join-Path $Root 'adapters')) -and
        (Test-Path -LiteralPath (Join-Path $Root 'content'))
    )
}

function Resolve-RulesSource {
    param([string]$Requested)
    if ($Requested) { return $Requested }
    if ($env:AI_RULES_1C_SOURCE) { return $env:AI_RULES_1C_SOURCE }

    $cursor = $PSScriptRoot
    for ($i = 0; $i -lt 6 -and $cursor; $i++) {
        if (Test-SourceTree $cursor) { return (Get-NormalizedPath $cursor) }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or (Test-SamePath $parent $cursor)) { break }
        $cursor = $parent
    }

    return $script:DefaultSourceUrl
}

function Resolve-HostTool {
    param([string]$Requested)
    if ($Requested -and $Requested -ne 'auto') { return $Requested }
    if ($env:CLAUDE_PLUGIN_ROOT) { return 'claude-code' }
    if ($env:CURSOR_PLUGIN_ROOT -or $env:CURSOR_TRACE_ID -or $env:CURSOR_AGENT) { return 'cursor' }
    if ($env:CODEX_HOME -or $env:CODEX_PLUGIN_ROOT) { return 'codex' }
    if ($env:OPENCODE) { return 'opencode' }
    if ($env:KILO_CLI -or $env:KILOCODE) { return 'kilocode' }
    return ''
}

function Resolve-TargetProjectRoot {
    param([string]$Requested)
    if ($Requested) { return (Get-NormalizedPath $Requested) }
    if ($env:CURSOR_PROJECT_DIR) { return (Get-NormalizedPath $env:CURSOR_PROJECT_DIR) }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $top = & git rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -eq 0 -and $top) { return (Get-NormalizedPath $top.Trim()) }
    }

    return (Get-NormalizedPath (Get-Location).Path)
}

function Test-SourceIsUrl {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    if ($Value -match '^(https?|git|ssh)://') { return $true }
    if ($Value -match '^git@[^:]+:.+') { return $true }
    if ($Value -match '\.git/?$') { return $true }
    return $false
}

function Get-SourceTreeFromUrl {
    param([string]$Url)
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        throw "Source is a URL ($Url) but git was not found in PATH."
    }
    $cacheRoot = if ($env:TEMP) { $env:TEMP } else { [System.IO.Path]::GetTempPath() }
    $cacheDir = Join-Path $cacheRoot '1c-rules-source-marketplace'
    if (Test-Path (Join-Path $cacheDir '.git')) {
        & git -C $cacheDir fetch --depth 1 origin HEAD 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "git fetch failed for $Url (exit $LASTEXITCODE)." }
        & git -C $cacheDir reset --hard FETCH_HEAD 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "git reset failed for $Url (exit $LASTEXITCODE)." }
    }
    else {
        if (Test-Path $cacheDir) { Remove-Item -Recurse -Force $cacheDir }
        & git clone --depth 1 $Url $cacheDir 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0 -or -not (Test-SourceTree $cacheDir)) {
            throw "git clone failed for $Url (exit $LASTEXITCODE)."
        }
    }
    return (Get-NormalizedPath $cacheDir)
}

function New-Plan {
    param(
        [string]$Action,
        [string]$Reason,
        [string]$Project,
        [string]$SourceRoot,
        [string]$HostTool,
        [string]$Installer
    )
    return [ordered]@{
        action      = $Action
        reason      = $Reason
        projectRoot = $Project
        source      = $SourceRoot
        tool        = $HostTool
        installer   = $Installer
    }
}

function Get-BootstrapPlan {
    param(
        [string]$CommandName,
        [string]$RequestedTool,
        [string]$RequestedProject,
        [string]$RequestedSource
    )

    $project = Resolve-TargetProjectRoot -Requested $RequestedProject
    $sourceRoot = Resolve-RulesSource -Requested $RequestedSource
    $hostTool = Resolve-HostTool -Requested $RequestedTool
    $installer = ''
    if (Test-SourceTree $sourceRoot) {
        $installer = Join-Path $sourceRoot 'install.ps1'
    }

    if (-not $project -or -not (Test-Path -LiteralPath $project)) {
        return (New-Plan -Action 'skip' -Reason 'missing-project' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
    }
    if (Test-ForbiddenProjectRoot $project) {
        return (New-Plan -Action 'skip' -Reason 'forbidden-root' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
    }

    $manifestTools = Get-ManifestTools -Root $project

    switch ($CommandName) {
        'doctor' {
            return (New-Plan -Action 'doctor' -Reason 'explicit' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
        }
        'update' {
            if ($null -eq $manifestTools) {
                return (New-Plan -Action 'skip' -Reason 'no-manifest' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
            }
            return (New-Plan -Action 'update' -Reason 'explicit' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
        }
        'init' {
            if (-not $hostTool) {
                return (New-Plan -Action 'skip' -Reason 'no-tool' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
            }
            return (New-Plan -Action 'init' -Reason 'explicit' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
        }
        default {
            if ($null -eq $manifestTools) {
                if (-not (Test-OneCProjectRoot $project)) {
                    return (New-Plan -Action 'skip' -Reason 'not-1c-project' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
                }
                if (-not $hostTool) {
                    return (New-Plan -Action 'skip' -Reason 'no-tool' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
                }
                return (New-Plan -Action 'init' -Reason 'first-install' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
            }
            if (-not $hostTool) {
                return (New-Plan -Action 'skip' -Reason 'already-installed' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
            }
            if ($manifestTools -contains $hostTool) {
                return (New-Plan -Action 'skip' -Reason 'already-installed' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
            }
            return (New-Plan -Action 'add' -Reason 'missing-tool' -Project $project -SourceRoot $sourceRoot -HostTool $hostTool -Installer $installer)
        }
    }
}

function Invoke-InstallPlan {
    param($Plan)
    if ($Plan.action -eq 'skip') {
        Write-Host ("1c-rules bootstrap: skip ({0})" -f $Plan.reason)
        return 0
    }

    $sourceRoot = [string]$Plan.source
    if (Test-SourceIsUrl $sourceRoot) {
        $sourceRoot = Get-SourceTreeFromUrl -Url $sourceRoot
    }
    if (-not (Test-SourceTree $sourceRoot)) {
        throw "Rules source is not an install.ps1 tree: $sourceRoot"
    }
    $installPs1 = Join-Path $sourceRoot 'install.ps1'

    switch ($Plan.action) {
        'init'   { $fileArgs = @('init', '-Tools', $Plan.tool, '-ProjectRoot', $Plan.projectRoot, '-Source', $sourceRoot, '-AssumeYes', '-NonInteractive') }
        'add'    { $fileArgs = @('add', '-Tool', $Plan.tool, '-ProjectRoot', $Plan.projectRoot, '-Source', $sourceRoot, '-AssumeYes', '-NonInteractive') }
        'update' { $fileArgs = @('update', '-ProjectRoot', $Plan.projectRoot, '-Source', $sourceRoot, '-AssumeYes', '-NonInteractive') }
        'doctor' { $fileArgs = @('doctor', '-ProjectRoot', $Plan.projectRoot) }
        default  { throw "Unknown plan action: $($Plan.action)" }
    }

    Write-Host ("1c-rules bootstrap: {0} tool={1} project={2}" -f $Plan.action, $Plan.tool, $Plan.projectRoot)
    & $installPs1 @fileArgs
    return $LASTEXITCODE
}

$plan = Get-BootstrapPlan -CommandName $Action -RequestedTool $Tool -RequestedProject $ProjectRoot -RequestedSource $Source

if ($DryRun) {
    $plan | ConvertTo-Json -Compress
    exit 0
}

try {
    $code = Invoke-InstallPlan -Plan $plan
    if ($null -eq $code) { $code = 0 }
    exit $code
}
catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    exit 1
}

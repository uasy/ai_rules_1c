#Requires -Version 5.1
<# Offline regressions: rules installation must not own an existing OpenCode config. #>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Installer = Join-Path $RepoRoot 'install.ps1'
$ShellPath = (Get-Process -Id $PID).Path
$Work = Join-Path ([IO.Path]::GetTempPath()) ('opencode-config-' + [guid]::NewGuid().ToString('N'))
$SourceRoot = Join-Path $Work 'source'
$Utf8 = New-Object Text.UTF8Encoding $false
$script:Passed = 0
$ConfigPaths = @('opencode.json', 'opencode.jsonc', '.opencode/opencode.json', '.opencode/opencode.jsonc')

function Write-Fixture([string]$Path, [string]$Text) {
    [void][IO.Directory]::CreateDirectory((Split-Path $Path -Parent))
    [IO.File]::WriteAllText($Path, $Text, $Utf8)
}
function Assert-True($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Read-Json([string]$Path) { Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json }
function Invoke-Installer([string]$Project, [string[]]$Arguments) {
    $log = Join-Path $Work ('run-' + [guid]::NewGuid().ToString('N') + '.log')
    & $ShellPath -NoProfile -ExecutionPolicy Bypass -File $Installer @Arguments `
        -ProjectRoot $Project -Source $SourceRoot -NonInteractive -McpMode managed *> $log
    Assert-True ($LASTEXITCODE -eq 0) "Installer failed: $(Get-Content -LiteralPath $log -Raw)"
}
function Assert-Preserved([string]$Project, [hashtable]$Hashes) {
    foreach ($rel in $ConfigPaths) {
        $path = Join-Path $Project $rel
        if ($Hashes.ContainsKey($rel)) {
            Assert-True (Test-Path -LiteralPath $path) "Config deleted: $rel"
            Assert-True ((Get-FileHash -LiteralPath $path).Hash -eq $Hashes[$rel]) "Config changed: $rel"
        }
        else { Assert-True (-not (Test-Path -LiteralPath $path)) "Unexpected duplicate config: $rel" }
    }
    $manifestPath = Join-Path $Project '.ai-rules.json'
    if (Test-Path -LiteralPath $manifestPath) {
        $manifest = Read-Json $manifestPath
        foreach ($rel in $ConfigPaths) {
            Assert-True ($rel -notin @($manifest.files.PSObject.Properties.Name)) "User config still managed: $rel"
        }
    }
}
function Track-OldConfigs([string]$Project, [hashtable]$Hashes) {
    $path = Join-Path $Project '.ai-rules.json'
    $manifest = Read-Json $path
    foreach ($rel in $Hashes.Keys) {
        $entry = @{ source = 'content/mcp-servers.json'; installedHash = $Hashes[$rel].ToLowerInvariant() }
        if ($rel -eq 'opencode.json') { $entry.merged = $true; $entry.mergeKey = 'mcp' }
        $manifest.files | Add-Member -NotePropertyName $rel -NotePropertyValue $entry -Force
    }
    Write-Fixture $path ($manifest | ConvertTo-Json -Depth 30)
}
function Pass([string]$Name) { $script:Passed++; Write-Host "OK  $Name" }

try {
    [void][IO.Directory]::CreateDirectory($SourceRoot)
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'adapters') -Destination $SourceRoot -Recurse
    foreach ($file in @('AGENTS.md', 'USER-RULES.md', 'memory.md', 'LLM-RULES.md')) {
        Write-Fixture (Join-Path $SourceRoot $file) "# $file"
    }
    foreach ($dir in @('rules', 'agents', 'commands', 'skills')) {
        [void][IO.Directory]::CreateDirectory((Join-Path $SourceRoot "content/$dir"))
    }
    Write-Fixture (Join-Path $SourceRoot 'content/rules/probe.md') "---`ndescription: Fixture`nalwaysApply: false`n---`n# Probe"
    Write-Fixture (Join-Path $SourceRoot 'content/mcp-servers.json') '{"servers":[{"id":"1c-fixture","url":"http://127.0.0.1:1/mcp"}]}'
    $userConfig = '{"model":"user-model","mcp":{"onec-fixture":{"type":"remote","url":"http://localhost:9999/custom","enabled":false,"headers":{"X-Test":"fixture"}},"custom":{"type":"local","command":["node","mine.js"],"environment":{"FIXTURE":"yes"}}},"permission":{"bash":"ask"}}'

    foreach ($rel in $ConfigPaths) {
        $project = Join-Path $Work ($rel.Replace('/', '-'))
        $text = if ($rel.EndsWith('.jsonc')) { "// keep comments and formatting`r`n" + $userConfig.Replace('"model":"user-model",', '"model":"user-model", /* user setting */') } else { $userConfig }
        Write-Fixture (Join-Path $project $rel) $text
        $hashes = @{ $rel = (Get-FileHash -LiteralPath (Join-Path $project $rel)).Hash }
        Invoke-Installer $project @('init')
        Assert-True ('opencode' -in (Read-Json (Join-Path $project '.ai-rules.json')).tools) 'OpenCode not detected'
        Assert-Preserved $project $hashes
        Track-OldConfigs $project $hashes
        Invoke-Installer $project @('update', '-Force')
        Assert-Preserved $project $hashes
        Invoke-Installer $project @('update')
        Assert-Preserved $project $hashes
        Track-OldConfigs $project $hashes
        Invoke-Installer $project @('remove', '-Tool', 'opencode')
        Assert-Preserved $project $hashes
        Pass "${rel}: init, old-manifest forced update, repeated update, scoped remove"
    }

    $project = Join-Path $Work 'both-configs'
    $hashes = @{}
    foreach ($rel in @('opencode.json', '.opencode/opencode.json')) {
        Write-Fixture (Join-Path $project $rel) ($userConfig.Replace('user-model', $rel))
        $hashes[$rel] = (Get-FileHash -LiteralPath (Join-Path $project $rel)).Hash
    }
    Invoke-Installer $project @('init', '-Tools', 'cursor')
    Invoke-Installer $project @('add', '-Tool', 'opencode')
    Assert-Preserved $project $hashes
    Track-OldConfigs $project $hashes
    Invoke-Installer $project @('remove')
    Assert-Preserved $project $hashes
    Pass 'both config locations: add and full remove with an old manifest'

    $project = Join-Path $Work 'malformed'
    Write-Fixture (Join-Path $project '.opencode/opencode.json') '{unfinished user edit'
    $hashes = @{ '.opencode/opencode.json' = (Get-FileHash -LiteralPath (Join-Path $project '.opencode/opencode.json')).Hash }
    Invoke-Installer $project @('init', '-Tools', 'opencode', '-Force')
    Assert-Preserved $project $hashes
    Pass 'malformed user config is never replaced with defaults'

    $project = Join-Path $Work 'fresh'
    [void][IO.Directory]::CreateDirectory($project)
    Invoke-Installer $project @('init', '-Tools', 'opencode')
    $config = Read-Json (Join-Path $project 'opencode.json')
    Assert-True ($config.mcp.'onec-fixture'.url -eq 'http://127.0.0.1:1/mcp') 'Fresh install did not render MCP'
    $hashes = @{ 'opencode.json' = (Get-FileHash -LiteralPath (Join-Path $project 'opencode.json')).Hash }
    Assert-Preserved $project $hashes
    Invoke-Installer $project @('update', '-ForcePaths', 'opencode.json')
    Assert-Preserved $project $hashes
    Invoke-Installer $project @('remove')
    Assert-Preserved $project $hashes
    Pass 'fresh config is created once and remains user-owned'

    Write-Host "PASS: $script:Passed OpenCode config scenarios ($($PSVersionTable.PSVersion))"
}
finally {
    $resolvedWork = [IO.Path]::GetFullPath($Work)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedWork.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test cleanup path' }
    if (Test-Path -LiteralPath $resolvedWork) { Remove-Item -LiteralPath $resolvedWork -Recurse -Force }
}

# Подключает скилл field-notes к Claude Code и Codex CLI: junction из этого репозитория
# в ~/.claude/skills/field-notes и ~/.codex/skills/field-notes. Одна копия, два агента.
#
#   pwsh -File install.ps1            подключить туда, где найден каталог агента
#   pwsh -File install.ps1 -Force     перезаписать существующие ссылки
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$home_ = $HOME
if (-not $home_) { $home_ = $env:USERPROFILE }

$targets = @(
    (Join-Path $home_ '.claude\skills\field-notes'),
    (Join-Path $home_ '.codex\skills\field-notes')
)

foreach ($dst in $targets) {
    $parent = Split-Path $dst -Parent
    $agent = Split-Path (Split-Path $parent -Parent) -Leaf
    if (-not (Test-Path (Split-Path $parent -Parent))) {
        Write-Host "- $agent не установлен, пропускаю"
        continue
    }
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
    if (Test-Path $dst) {
        $item = Get-Item $dst -Force
        if (-not $Force) {
            Write-Host "! $dst уже существует — запусти с -Force, чтобы заменить"
            continue
        }
        if ($item.LinkType) { $item.Delete() } else { Remove-Item $dst -Recurse -Force }
    }
    New-Item -ItemType Junction -Path $dst -Target $src | Out-Null
    Write-Host "+ $agent -> $dst"
}

# Хранилище заметок: общее для всех агентов, по умолчанию ~/.claude/field-notes
$root = $env:FIELD_NOTES_DIR
if (-not $root) {
    $claudeRoot = Join-Path $home_ '.claude\field-notes'
    $codexRoot = Join-Path $home_ '.codex\field-notes'
    $root = if (Test-Path $claudeRoot) { $claudeRoot } elseif (Test-Path $codexRoot) { $codexRoot } else { $claudeRoot }
}
if (-not (Test-Path (Join-Path $root 'notes'))) {
    New-Item -ItemType Directory -Path (Join-Path $root 'notes') -Force | Out-Null
}
$index = Join-Path $root 'INDEX.md'
if (-not (Test-Path $index)) {
    @'
# Field Notes

Инженерные находки, которые переживают отдельный проект: root cause, workaround, грабли
инструмента, кандидаты в скиллы. Общее хранилище для всех агентов на машине.
Как вести — скилл `field-notes`.

## Индекс

| Date | Note | Area | Status | Candidate skill | Summary |
|---|---|---|---|---|---|
'@ | Set-Content -Path $index -Encoding utf8
    Write-Host "+ создан $index"
}
Write-Host "хранилище заметок: $root"

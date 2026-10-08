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
    # индекс с маркером генерации собирает fieldnotes.py; без Python — пустой файл, lint попросит index
    $py = $null
    $candidates = @(
        @{ Exe = 'py'; Args = @('-3') },
        @{ Exe = 'python3'; Args = @() },   # из WindowsApps — заглушка магазина, отсеется пробным запуском
        @{ Exe = 'python'; Args = @() }
    )
    foreach ($cand in $candidates) {
        try {
            & $cand.Exe @($cand.Args) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { $py = $cand; break }
        } catch {}
    }
    $script = Join-Path (Join-Path $src 'scripts') 'fieldnotes.py'
    if ($py) {
        & $py.Exe @($py.Args) $script init --root $root | Out-Null
    } else {
        "# Field Notes`n`nИндекс собирает ``fieldnotes.py index`` (нужен Python 3.9+).`n" | Set-Content -Path $index -Encoding utf8
        Write-Host "! Python 3.9+ не найден: поиск, индекс и lint работать не будут"
    }
    Write-Host "+ создан $index"
}
Write-Host "хранилище заметок: $root"

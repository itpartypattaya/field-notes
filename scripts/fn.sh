#!/bin/sh
# field-notes helper. POSIX sh: Git Bash, WSL, Linux, macOS.
#
#   sh fn.sh root              вывести корень хранилища
#   sh fn.sh init              создать пустое хранилище (INDEX.md + notes/)
#   sh fn.sh new <slug>        создать заметку по шаблону с сегодняшней датой
#   sh fn.sh grep <текст>      искать по индексу и заметкам
#   sh fn.sh list              последние заметки по дате изменения
#
# Корень: $FIELD_NOTES_DIR -> ~/.claude/field-notes -> ~/.codex/field-notes -> ~/.claude/field-notes
set -eu

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TEMPLATE="$SELF_DIR/../assets/note-template.md"

fn_home() {
  if [ -n "${HOME:-}" ]; then
    printf '%s\n' "$HOME"
  elif [ -n "${USERPROFILE:-}" ]; then
    printf '%s\n' "$USERPROFILE"
  else
    echo "fn.sh: не найден домашний каталог (HOME/USERPROFILE)" >&2
    exit 1
  fi
}

fn_root() {
  if [ -n "${FIELD_NOTES_DIR:-}" ]; then
    printf '%s\n' "$FIELD_NOTES_DIR"
    return
  fi
  home=$(fn_home)
  if [ -d "$home/.claude/field-notes" ]; then
    printf '%s\n' "$home/.claude/field-notes"
  elif [ -d "$home/.codex/field-notes" ]; then
    printf '%s\n' "$home/.codex/field-notes"
  else
    printf '%s\n' "$home/.claude/field-notes"
  fi
}

fn_init() {
  root=$(fn_root)
  mkdir -p "$root/notes"
  if [ ! -f "$root/INDEX.md" ]; then
    cat > "$root/INDEX.md" <<'EOF'
# Field Notes

Инженерные находки, которые переживают отдельный проект: root cause, workaround, грабли
инструмента, кандидаты в скиллы. Общее хранилище для всех агентов на машине.
Как вести — скилл `field-notes`.

## Индекс

| Date | Note | Area | Status | Candidate skill | Summary |
|---|---|---|---|---|---|
EOF
    echo "создан $root/INDEX.md"
  fi
  echo "$root"
}

fn_new() {
  slug=${1:-}
  if [ -z "$slug" ]; then
    echo "usage: fn.sh new <short-slug>" >&2
    exit 2
  fi
  root=$(fn_root)
  mkdir -p "$root/notes"
  [ -f "$root/INDEX.md" ] || fn_init >/dev/null
  date=$(date +%F)
  path="$root/notes/$date-$slug.md"
  if [ -e "$path" ]; then
    echo "уже существует: $path — это обновление, а не новая заметка" >&2
    exit 3
  fi
  if [ -f "$TEMPLATE" ]; then
    sed "s/YYYY-MM-DD/$date/" "$TEMPLATE" > "$path"
  else
    printf '# \n- **Date:** %s · **Area:**  · **Status:** active\n' "$date" > "$path"
  fi
  printf '%s\n' "$path"
  echo "не забудь строку в $root/INDEX.md (новые — сверху)" >&2
}

fn_grep() {
  if [ $# -eq 0 ]; then
    echo "usage: fn.sh grep <текст>" >&2
    exit 2
  fi
  root=$(fn_root)
  [ -d "$root" ] || { echo "хранилища нет: $root (fn.sh init)" >&2; exit 4; }
  grep -rin --color=auto -- "$1" "$root/INDEX.md" "$root/notes" 2>/dev/null || {
    echo "совпадений нет: $1" >&2
    exit 1
  }
}

fn_list() {
  root=$(fn_root)
  [ -d "$root/notes" ] || { echo "хранилища нет: $root (fn.sh init)" >&2; exit 4; }
  ls -t "$root/notes"
}

cmd=${1:-}
[ $# -gt 0 ] && shift || true
case "$cmd" in
  root) fn_root ;;
  init) fn_init ;;
  new)  fn_new "$@" ;;
  grep) fn_grep "$@" ;;
  list) fn_list ;;
  *)    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' ;;
esac

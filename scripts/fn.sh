#!/bin/sh
# field-notes helper. POSIX sh: Git Bash, WSL, Linux, macOS.
#
#   sh fn.sh root                       корень хранилища
#   sh fn.sh init                       создать пустое хранилище (INDEX.md + notes/)
#   sh fn.sh new <slug> [--title "…"]   заметка по шаблону с сегодняшней датой
#   sh fn.sh grep <текст>               сырой поиск строки по индексу и заметкам
#   sh fn.sh search <слова…>            поиск с ранжированием (title > tags > area/summary > тело)
#   sh fn.sh list                       последние заметки по дате правки
#   sh fn.sh index | lint               пересобрать INDEX.md | проверить хранилище
#   sh fn.sh touch <id> [--status …]    отметить обновление заметки
#   sh fn.sh issue-draft <id>           черновик issue для автора инструмента (с маской)
#   sh fn.sh migrate --from <dir> [--apply]
#
# Всё, кроме grep, делает scripts/fieldnotes.py (Python >= 3.9). Без Python работают root, init,
# new, grep и list в упрощённом виде.
# Корень: $FIELD_NOTES_DIR -> ~/.claude/field-notes -> ~/.codex/field-notes -> ~/.claude/field-notes
set -eu

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PY_SCRIPT="$SELF_DIR/fieldnotes.py"
TEMPLATE="$SELF_DIR/../assets/note-template.md"

# Python: $FIELD_NOTES_PYTHON -> py -3 (Windows) -> python3 -> python. Каждый кандидат запускается
# пробно: python3 из WindowsApps — заглушка магазина, которая есть в PATH, но не работает.
find_python() {
  for cand in "${FIELD_NOTES_PYTHON:-}" "py -3" python3 python; do
    [ -n "$cand" ] || continue
    if $cand -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$cand"
      return 0
    fi
  done
  return 1
}

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

# --- упрощённые команды на случай, когда Python нет ---

fallback_init() {
  root=$(fn_root)
  mkdir -p "$root/notes"
  [ -f "$root/INDEX.md" ] || printf '# Field Notes\n\nИндекс собирает `fieldnotes.py index` (нужен Python).\n' > "$root/INDEX.md"
  printf '%s\n' "$root"
}

fallback_new() {
  slug=${1:-}
  [ -n "$slug" ] || { echo "usage: fn.sh new <short-slug>" >&2; exit 2; }
  root=$(fallback_init)
  date=$(date +%F)
  path="$root/notes/$date-$slug.md"
  if ls "$root/notes/"*"-$slug.md" >/dev/null 2>&1; then
    echo "заметка с таким slug уже есть — это обновление, а не новая заметка" >&2
    exit 3
  fi
  sed -e "s/{{id}}/$date-$slug/" -e "s/{{date}}/$date/" \
      -e 's/{{title_yaml}}/"<Заголовок-утверждение>"/' -e 's/{{title}}/<Заголовок-утверждение>/' \
      -e 's/{{area_yaml}}/"<инструмент \/ область>"/' "$TEMPLATE" > "$path"
  printf '%s\n' "$path"
  echo "Python не найден: индекс не пересобран — добавь строку в INDEX.md руками" >&2
}

cmd=${1:-}
[ $# -gt 0 ] && shift || true

case "$cmd" in
  grep) fn_grep "$@"; exit ;;
  root) fn_root; exit ;;   # в sh: путь в том же виде, что у вызывающего шелла
  ""|-h|--help|help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
esac

if PY=$(find_python); then
  # shellcheck disable=SC2086  # "py -3" — две части намеренно
  exec $PY "$PY_SCRIPT" "$cmd" "$@"
fi

case "$cmd" in
  root) fn_root ;;
  init) fallback_init ;;
  new)  fallback_new "$@" ;;
  list) ls -t "$(fn_root)/notes" ;;
  *)    echo "fn.sh $cmd: нужен Python >= 3.9 (или задай FIELD_NOTES_PYTHON)" >&2; exit 1 ;;
esac

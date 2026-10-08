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

# Общие флаги разбираем и в sh: --root, --read-only, --json (Python разбирает их сам)
ROOT_OPT=""
READ_ONLY=""
AS_JSON=""
POS1=""
parse_flags() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --root) ROOT_OPT=${2:-}; [ $# -gt 1 ] && shift ;;
      --root=*) ROOT_OPT=${1#--root=} ;;
      --read-only) READ_ONLY=1 ;;
      --json) AS_JSON=1 ;;
      -*) ;;
      *) [ -n "$POS1" ] || POS1=$1 ;;
    esac
    shift
  done
}

fn_root() {
  if [ -n "$ROOT_OPT" ]; then
    printf '%s\n' "$ROOT_OPT"
    return
  fi
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

json_escape() {  # минимальное экранирование строки для JSON: \ и "
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

fn_grep() {
  if [ -z "$POS1" ]; then
    echo "usage: fn.sh grep <точная строка>" >&2
    exit 2
  fi
  root=$(fn_root)
  [ -d "$root" ] || { echo "хранилища нет: $root (fn.sh init)" >&2; exit 4; }
  # строка ищется буквально: спецсимволы BRE экранируются («[x]» — это «[x]», а не класс символов).
  # Не `grep -iF`: GNU grep 3.0 из Git for Windows на нём падает (Aborted, код 134) на кириллице.
  pat=$(printf '%s' "$POS1" | sed 's/[][\\.*^$]/\\&/g')
  set +e
  grep -rin -- "$pat" "$root/INDEX.md" "$root/notes"
  rc=$?
  set -e
  case $rc in
    0) ;;
    1) echo "совпадений нет: $POS1" >&2; exit 1 ;;
    *) echo "fn.sh grep: ошибка поиска (код $rc)" >&2; exit 2 ;;
  esac
}

# --- упрощённые команды на случай, когда Python нет ---

fallback_init() {
  if [ -n "$READ_ONLY" ]; then echo "--read-only: отказываюсь создавать хранилище" >&2; exit 1; fi
  root=$(fn_root)
  mkdir -p "$root/notes"
  if [ ! -f "$root/INDEX.md" ]; then
    ( set -C; printf '# Field Notes\n\nИндекс собирает `fieldnotes.py index` (нужен Python).\n' > "$root/INDEX.md" ) 2>/dev/null || true
  fi
  printf '%s\n' "$root"
}

fallback_new() {
  if [ -n "$READ_ONLY" ]; then echo "--read-only: отказываюсь создавать заметку" >&2; exit 1; fi
  slug=$POS1
  case "$slug" in
    ""|-*|*[!a-z0-9-]*) echo "usage: fn.sh new <slug>: латиница в нижнем регистре, цифры и '-'" >&2; exit 2 ;;
  esac
  root=$(fallback_init)
  date=$(date +%F)
  path="$root/notes/$date-$slug.md"
  if ls "$root/notes/"*"-$slug.md" >/dev/null 2>&1; then
    echo "заметка с таким slug уже есть — это обновление, а не новая заметка" >&2
    exit 3
  fi
  # set -C (noclobber): '>' не перезапишет файл, если параллельный вызов успел создать его первым
  if ! ( set -C
         sed -e "s/{{id}}/$date-$slug/" -e "s/{{date}}/$date/" \
             -e 's/{{title_yaml}}/"<Заголовок-утверждение>"/' -e 's/{{title}}/<Заголовок-утверждение>/' \
             -e 's/{{area_yaml}}/"<инструмент \/ область>"/' "$TEMPLATE" > "$path" ) 2>/dev/null; then
    echo "заметка только что появилась: $path — не перезаписываю" >&2
    exit 3
  fi
  printf '%s\n' "$path"
  echo "Python не найден: индекс не пересобран — добавь строку в INDEX.md руками" >&2
}

cmd=${1:-}
[ $# -gt 0 ] && shift || true
parse_flags "$@"

case "$cmd" in
  grep) fn_grep; exit ;;
  root)   # в sh: путь в том же виде, что у вызывающего шелла
    if [ -n "$AS_JSON" ]; then
      r=$(fn_root)
      if [ -d "$r/notes" ]; then e=true; else e=false; fi
      printf '{"root": "%s", "exists": %s}\n' "$(json_escape "$r")" "$e"
    else
      fn_root
    fi
    exit ;;
  ""|-h|--help|help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
esac

if [ -z "${FIELD_NOTES_NO_PYTHON:-}" ] && PY=$(find_python); then   # FIELD_NOTES_NO_PYTHON — для тестов
  # shellcheck disable=SC2086  # "py -3" — две части намеренно
  exec $PY "$PY_SCRIPT" "$cmd" "$@"
fi

case "$cmd" in
  init) fallback_init ;;
  new)  fallback_new ;;
  list) ls -t "$(fn_root)/notes" ;;
  *)    echo "fn.sh $cmd: нужен Python >= 3.9 (или задай FIELD_NOTES_PYTHON)" >&2; exit 1 ;;
esac

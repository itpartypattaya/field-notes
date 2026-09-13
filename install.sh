#!/bin/sh
# Подключает скилл field-notes к Claude Code и Codex CLI симлинком из этого репозитория.
# Одна копия, два агента.  Использование: sh install.sh [--force]
set -eu

src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
force=${1:-}
home=${HOME:-${USERPROFILE:-}}
[ -n "$home" ] || { echo "не найден домашний каталог" >&2; exit 1; }

for agent in .claude .codex; do
  [ -d "$home/$agent" ] || { echo "- $agent не установлен, пропускаю"; continue; }
  dst="$home/$agent/skills/field-notes"
  mkdir -p "$home/$agent/skills"
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    if [ "$force" = "--force" ]; then
      rm -rf "$dst"
    else
      echo "! $dst уже существует — запусти с --force"
      continue
    fi
  fi
  ln -s "$src" "$dst"
  echo "+ $agent -> $dst"
done

sh "$src/scripts/fn.sh" init

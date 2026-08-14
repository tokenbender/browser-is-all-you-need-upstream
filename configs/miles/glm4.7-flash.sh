#!/usr/bin/env bash
# Compatibility adapter for repository launchers written before Miles moved
# model arguments from shell arrays to scripts/models/<model-type>.py.

MILES_ROOT="${MILES_ROOT:-/root/miles}"
MODEL_ARGS_LOADER="${MILES_ROOT}/miles/utils/external_utils/model_args_utils.py"
if [ ! -f "${MODEL_ARGS_LOADER}" ]; then
  echo "Missing Miles model-args loader: ${MODEL_ARGS_LOADER}" >&2
  return 2
fi

MODEL_ARGS_LINE="$("${MILES_PYTHON:-python3}" "${MODEL_ARGS_LOADER}" "glm4.7-flash")" || return 2
read -r -a MODEL_ARGS <<<"${MODEL_ARGS_LINE}"
if [ "${#MODEL_ARGS[@]}" -eq 0 ]; then
  echo "Miles returned no GLM-4.7-Flash model arguments" >&2
  return 2
fi

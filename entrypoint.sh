#!/bin/sh
# Запуск приложения от непривилегированного пользователя (uid 1000).
# Права на data/ и app/ выставляются при каждом старте — так работают и старые
# данные (созданные root'ом), и обновление через интерфейс.
# Если сменить пользователя не получилось — запускаемся как раньше, от root.
# Отключить: переменная окружения OOPS_RUN_AS_ROOT=1.
APP_UID="${OOPS_UID:-1000}"
APP_GID="${OOPS_GID:-1000}"

if [ "$(id -u)" = "0" ] && [ "${OOPS_RUN_AS_ROOT:-0}" != "1" ] && command -v setpriv >/dev/null 2>&1; then
    mkdir -p /app/data
    if chown -R "$APP_UID:$APP_GID" /app/data /app/app 2>/dev/null \
       && setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups true 2>/dev/null; then
        exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"
    fi
    echo "entrypoint: не удалось сменить пользователя, запуск от root" >&2
fi
exec "$@"

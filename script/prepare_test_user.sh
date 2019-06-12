#! /bin/bash
set -euo pipefail

PRIMEHUB_PATH=${PRIMEHUB_PATH:-"~/primehub-latest"}
KC_USER_CREATE=""

function print_usage() {
  >&2 echo "Usage: `basename $0` <prefix> <count>"
}

function check_primehub_path() {
    if [[ ! -d "$PRIMEHUB_PATH" ]]; then
        >&2 echo "[Failed] Should provide correct PRIEHUB_PATH. (Current: $PRIMEHUB_PATH)"
        return 1
    fi
    if [[ ! -f "$PRIMEHUB_PATH/modules/bootstrap/kc_user_create.sh" ]]; then
        >&2 echo "[Failed] PrimeHub version is not correct."
        >&2 echo "         Current: $(cat $PRIMEHUB_PATH/VERSION) Require: primehub-v1.5.0"
        return 1
    else
        KC_USER_CREATE="$PRIMEHUB_PATH/modules/bootstrap/kc_user_create.sh"
    fi
}

if [[ $# != 2 ]]; then
    print_usage
    exit 1
fi

username_prefix=$1
count=$2

check_primehub_path; rc=$?
if [[ "$rc" != 0 ]]; then
    exit 1
fi

for i in $(seq 0 $(($count-1))); do
    name="$username_prefix-$i"
    $KC_USER_CREATE primehub $name hello phusers
done

echo "[Done] generate user $username_prefix-0 ~ $username_prefix-$(($count-1))"
#!/usr/bin/env bash

set -e
set -x
export SHELLOPTS

source tests/test_utils.sh

wait_for_registry

test_push_catalog_pull

echo "OK"

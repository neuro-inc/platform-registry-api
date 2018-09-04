#!/usr/bin/env bash

set -e
set -x
export SHELLOPTS


function wait_for_registry() {
    local cmd="curl http://localhost:5000/v2/ &> /dev/null"
    # this for loop waits until the registry api is available
    for _ in {1..150}; do # timeout for 5 minutes
        if eval "$cmd"; then
            break
        fi
        sleep 2
    done
    docker login -u neuromation -p neuromation localhost:5000
}


function test_pull_non_existent() {
    local output=$(docker pull localhost:5000/unknown:latest 2>&1)
    [[ $output == *"manifest for localhost:5000/unknown:latest not found"* ]]
}


function test_push_pull() {
    docker rmi ubuntu:latest localhost:5000/ubuntu:latest || :
    docker pull ubuntu:latest
    docker tag ubuntu:latest localhost:5000/ubuntu:latest
    docker push localhost:5000/ubuntu:latest
    docker rmi ubuntu:latest localhost:5000/ubuntu:latest
    docker pull localhost:5000/ubuntu:latest
}

wait_for_registry
test_pull_non_existent
test_push_pull

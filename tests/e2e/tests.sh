#!/usr/bin/env bash

set -e
set -x
export SHELLOPTS


function generate_user_token() {
    local name=$1
    local auth_image="gcr.io/light-reality-205619/platformauthapi:latest"
    local auth_container=$(docker ps --filter "ancestor=$auth_image" --filter "status=running" -q)
    docker exec $auth_container platform-auth-make-token $name
}

function create_regular_user() {
    local name=$1
    local data="{\"name\": \"$name\"}"
    curl --fail --data "$data" -H "Authorization: Bearer $ADMIN_TOKEN" \
        http://localhost:5003/api/v1/users
}


function wait_for_registry() {
    local cmd="curl http://localhost:5000/v2/ &> /dev/null"
    # this for loop waits until the registry api is available
    for _ in {1..150}; do # timeout for 5 minutes
        if eval "$cmd"; then
            break
        fi
        sleep 2
    done
}


function log_into_registry() {
    local name=$1
    local token=$2
    docker login -u $name -p $token localhost:5000
}


function test_pull_non_existent() {
    local name=$1
    local output=$(docker pull localhost:5000/$name/unknown:latest 2>&1)
    [[ $output == *"manifest for localhost:5000/$name/unknown:latest not found"* ]]
}


function test_push_pull() {
    local name=$1
    docker rmi ubuntu:latest localhost:5000/$name/ubuntu:latest || :
    docker pull ubuntu:latest
    docker tag ubuntu:latest localhost:5000/$name/ubuntu:latest
    docker push localhost:5000/$name/ubuntu:latest
    docker rmi ubuntu:latest localhost:5000/$name/ubuntu:latest
    docker pull localhost:5000/$name/ubuntu:latest
}


ADMIN_TOKEN=$(generate_user_token admin)

USER_NAME=$(uuidgen | awk '{print tolower($0)}')
USER_TOKEN=$(generate_user_token $USER_NAME)

wait_for_registry
create_regular_user $USER_NAME
log_into_registry $USER_NAME $USER_TOKEN
test_pull_non_existent $USER_NAME
test_push_pull $USER_NAME

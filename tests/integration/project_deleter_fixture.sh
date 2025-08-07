#!/usr/bin/env bash

set -e
set -x
export SHELLOPTS

source tests/test_utils.sh

# Push images to the registry for further project deletion tests

function create_regular_user() {
    local name=$1
    local data="{\"name\": \"$name\"}"
    curl --fail --data "$data" -H "Authorization: Bearer $ADMIN_TOKEN" \
        http://localhost:5003/api/v1/users
    # Grant permissions to the user images
    local url="http://localhost:5003/api/v1/users/$name/permissions"
    local data="[{\"uri\":\"image://$CLUSTER_NAME/org/project\",\"action\":\"manage\"}]"
    curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -d "$data" $url --fail
}

function push_test_fixture_images() {
    echo -e "\n"

    local name=$(uuidgen | awk '{print tolower($0)}')
    local token=$(generate_user_token $name)
    create_regular_user $name
    docker_login $name $token

    docker pull alpine:latest
    docker tag alpine:latest 127.0.0.1:5000/org/project/alpine:v1
    docker tag alpine:latest 127.0.0.1:5000/org/project/alpine:latest
    docker push 127.0.0.1:5000/org/project/alpine:latest
    docker push 127.0.0.1:5000/org/project/alpine:v1
}

push_test_fixture_images

echo "OK"

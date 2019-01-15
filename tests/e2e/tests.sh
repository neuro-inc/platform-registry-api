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


function test_push_catalog_pull() {
    local name=$1
    local token=$2
    docker rmi $name "ubuntu" || :
    docker rmi $name "alpine" || :
    docker_catalog $name $token ""

    docker_tag_push $name $token "ubuntu"
    expected="\"image://$name/ubuntu\""
    docker_catalog $name $token "$expected"

    docker_tag_push $name $token "alpine"
    expected="\"image://$name/alpine\", \"image://$name/ubuntu\""
    docker_catalog $name $token "$expected"

    docker rmi ubuntu:latest localhost:5000/$name/ubuntu:latest
    docker pull localhost:5000/$name/ubuntu:latest


    docker rmi alpine:latest localhost:5000/$name/alpine:latest
    docker pull localhost:5000/$name/alpine:latest
}

function docker_tag_push() {
    local name=$1
    local token=$2
    local image=$3
    docker pull $image:latest
    docker tag $image:latest localhost:5000/$name/$image:latest
    docker push localhost:5000/$name/$image:latest
}

function docker_catalog() {
    local name=$1
    local token=$2
    local expected="$3"
    local url="http://localhost:5000/v2/_catalog"
    local auth_basic_token=$(echo -n $name:$token | base64 -w 0)
    local output=$(curl -sH "Authorization: Basic $auth_basic_token" $url)
    echo $output | grep -w "{\"repositories\": \[""$expected""\]}"
}


function debug_test_docker_catalog_directly() {
    # the way to get auth token for accessing _catalog without using platform-registry-api:
    local auth_url="http://localhost:5001/auth?service=upstream&scope=registry:catalog:*"
    local auth_basic_token=$(echo -n testuser:testpassword | base64 -w 0)
    local registry_token=`curl -sH "Authorization: Basic $auth_basic_token" "$auth_url" | jq -r .token`
    # ...and then access the docker-registry directly:
    curl -vsH "Authorization: Bearer $registry_token" "http://localhost:5002/v2/_catalog"
    # NOTE (A Yushkovskiy, 25.12.2018) Read materials:
    # - on docker registry auth protocol:
    #   https://github.com/docker/distribution/blob/master/docs/spec/auth/token.md
    # - on docker listing catalog REST API:
    #   https://docs.docker.com/registry/spec/api/#listing-repositories
    # - examples of ACL rules for docker registry image:
    #   https://github.com/cesanta/docker_auth/blob/master/examples/reference.yml
}


ADMIN_TOKEN=$(generate_user_token admin)

USER_NAME=$(uuidgen | awk '{print tolower($0)}')
USER_TOKEN=$(generate_user_token $USER_NAME)

wait_for_registry
create_regular_user $USER_NAME
log_into_registry $USER_NAME $USER_TOKEN

test_pull_non_existent $USER_NAME
test_push_catalog_pull $USER_NAME $USER_TOKEN

echo "OK"


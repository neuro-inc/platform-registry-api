#!/usr/bin/env bash

set -e
set -x
export SHELLOPTS

CLUSTER_NAME=test-cluster

function fix_base64() {
    if command -v gbase64 >/dev/null 2>&1 ; then
        gbase64 "$@"
    else
        base64 "$@"
    fi
}

ORG=test-org
PROJECT=test-project

function generate_user_token() {
    local name=$1
    local auth_container=$(docker ps --filter name=auth_server -q)
    docker exec $auth_container platform-auth-make-token $name
}

function create_regular_user() {
    local name=$1
    local data="{\"name\": \"$name\"}"
    curl --fail --data "$data" -H "Authorization: Bearer $ADMIN_TOKEN" \
        http://localhost:5003/api/v1/users
    # Grant permissions to the user images
    local url="http://localhost:5003/api/v1/users/$name/permissions"
    local data="[{\"uri\":\"image://$CLUSTER_NAME/$ORG\",\"action\":\"manage\"}]"
    curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -d "$data" $url --fail
}

function share_resource_on_read() {
    local resource=$1
    local who_token=$2
    local whom=$3
    local url="http://localhost:5003/api/v1/users/$whom/permissions"
    local data="[{\"uri\":$resource,\"action\":\"read\"}]"
    curl -s -X POST -H "Authorization: Bearer $who_token" -d "$data" $url --fail
}

function wait_for_registry() {
    local cmd="curl http://127.0.0.1:5000/v2/ &> /dev/null"
    # this for loop waits until the registry api is available
    for _ in {1..150}; do # timeout for 5 minutes
        if eval "$cmd"; then
            break
        fi
        sleep 2
    done
}


function docker_login() {
    local name=$1
    local token=$2
    docker login -u $name -p $token 127.0.0.1:5000
}

function test_push_catalog_pull() {
    echo -e "\n"

    local name=$(uuidgen | awk '{print tolower($0)}')
    local token=$(generate_user_token $name)
    create_regular_user $name
    docker_login $name $token
    local repo_path="$ORG/$PROJECT"

    echo "step 1: pull non existent"
    local output=$(docker pull 127.0.0.1:5000/$repo_path/unknown:latest 2>&1)
    [[ $output == *"manifest for 127.0.0.1:5000/$repo_path/unknown:latest not found"* ]]

    echo "step 2: remove images and check catalog"
    docker rmi ubuntu:latest 127.0.0.1:5000/$repo_path/ubuntu:latest || :
    docker rmi alpine:latest 127.0.0.1:5000/$repo_path/alpine:latest || :
    test_catalog $name $token ""

    echo "step 3: push ubuntu, check catalog"
    docker_tag_push $name $token "ubuntu"
    local expected="\"$repo_path/ubuntu\""
    test_catalog $name $token "$expected"
    test_repo_tags_list $name $token "$repo_path/ubuntu"

    echo "step 4: push alpine, check catalog"
    docker_tag_push $name $token "alpine"
    local expected="\"$repo_path/alpine\", \"$repo_path/ubuntu\""
    test_catalog $name $token "$expected"

    echo "step 5: remove ubuntu, check pull"
    docker rmi ubuntu:latest
    docker pull 127.0.0.1:5000/$repo_path/ubuntu:latest

    echo "step 6: remove alpine, check pull"
    docker rmi alpine:latest
    docker pull 127.0.0.1:5000/$repo_path/alpine:latest
}


function docker_tag_push() {
    local name=$1
    local token=$2
    local image=$3
    docker pull $image:latest
    docker tag $image:latest 127.0.0.1:5000/$ORG/$PROJECT/$image:latest
    docker push 127.0.0.1:5000/$ORG/$PROJECT/$image:latest
}

function test_catalog() {
    local name=$1
    local token=$2
    local expected="$3"
    local url="http://127.0.0.1:5000/v2/_catalog?org=$ORG&project=$PROJECT"
    local auth_basic_token=$(echo -n $name:$token | fix_base64 -w 0)
    local output=$(curl -sH "Authorization: Basic $auth_basic_token" $url)
    echo $output | grep -w "{\"repositories\": \[$expected\]}"
}

function test_digest() {
    local name=$1
    local token=$2
    local image=$3
    local tag=$4
    local url="http://127.0.0.1:5000/v2/$image/manifests/$tag"
    local auth_basic_token=$(echo -n $name:$token | fix_base64 -w 0)
    local output=$(curl --verbose -sH "Authorization: Basic $auth_basic_token" $url 2>&1)
    echo $output | grep -w "Docker-Content-Digest:"
}

function test_repo_tags_list() {
    local name=$1
    local token=$2
    local repo="$3"
    local url="http://127.0.0.1:5000/v2/$repo/tags/list"
    local auth_basic_token=$(echo -n $name:$token | fix_base64 -w 0)
    local output=$(curl -sH "Authorization: Basic $auth_basic_token" $url)
    echo $output | grep "\"name\": \"$repo\""
    echo $output | grep "\"tags\": \["
}

function get_registry_token_for_catalog() {
    # the way to get auth token for accessing _catalog without using platform-registry-api:
    local username=$1
    local password=$2
    local registry_url=$3
    local service=$4
    local auth_url="$registry_url?service=$service&scope=registry:catalog:*"
    local auth_basic_token=$(echo -n $username:$password | fix_base64 -w 0)
    curl -sH "Authorization: Basic $auth_basic_token" "$auth_url" | jq -r .token
    # NOTE (A Yushkovskiy, 25.12.2018) Read materials:
    # - on docker registry auth protocol:
    #   https://github.com/docker/distribution/blob/master/docs/spec/auth/token.md
    # - on docker listing catalog REST API:
    #   https://docs.docker.com/registry/spec/api/#listing-repositories
    # - examples of ACL rules for docker registry image:
    #   https://github.com/cesanta/docker_auth/blob/master/examples/reference.yml
}

function debug_docker_catalog_local() {
    local user=testuser
    local password=testpassword
    local registry_token=`get_registry_token_for_catalog "$user" "$password" "http://localhost:5001/auth" "upstream"`
    curl -sH "Authorization: Bearer $registry_token" "http://localhost:5002/v2/_catalog" | jq
}

function debug_docker_catalog_gcr() {
    local user=$1
    local password=$2
    local registry_token=`get_registry_token_for_catalog "$user" "$password" "https://gcr.io/v2/token" "gcr.io"`
    curl -sH "Authorization: Bearer $registry_token" "https://gcr.io/v2/_catalog" | jq
}

ADMIN_TOKEN=$(generate_user_token admin)

wait_for_registry

test_push_catalog_pull

echo "OK"

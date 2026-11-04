from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from aiohttp.test_utils import TestServer as _TestServer
from aiohttp.web import Application, Request, Response, json_response

from platform_registry_api.config import UpstreamRegistryConfig, UpstreamType
from platform_registry_api.upstream_client import (
    ProjectImagesDeleteError,
    UpstreamV2ApiClient,
)


_TestServerFactory = Callable[[Application], Awaitable[_TestServer]]

OCI_INDEX = "application/vnd.oci.image.index.v1+json"


class _Registry:
    def __init__(self) -> None:
        self.tags = {
            "testproject/org/project/index": {"v1": ("sha256:index", OCI_INDEX)},
            "testproject/org/project/broken": {},
            "testproject/org/project/alpine": {
                "v1": (
                    "sha256:alpine",
                    "application/vnd.docker.distribution.manifest.v2+json",
                ),
                "bad": ("sha256:bad", "application/vnd.oci.image.manifest.v1+json"),
                "gone": ("sha256:gone", "application/vnd.oci.image.manifest.v1+json"),
            },
        }
        self.broken_digests = {"sha256:bad"}
        self.missing_tags = {"gone"}
        self.accept_headers: list[str] = []
        self.deleted: list[tuple[str, str]] = []

    def register(self, app: Application) -> None:
        app.router.add_get("/v2/_catalog", self.handle_catalog)
        app.router.add_get("/v2/{repo:.+}/tags/list", self.handle_tags)
        app.router.add_get("/v2/{repo:.+}/manifests/{tag}", self.handle_manifest)
        app.router.add_delete("/v2/{repo:.+}/manifests/{digest}", self.handle_delete)

    async def handle_catalog(self, request: Request) -> Response:
        return json_response({"repositories": list(self.tags)})

    async def handle_tags(self, request: Request) -> Response:
        repo = request.match_info["repo"]
        if repo.endswith("/broken"):
            return json_response({"errors": [{"code": "UNKNOWN"}]}, status=500)
        return json_response({"name": repo, "tags": list(self.tags[repo])})

    async def handle_manifest(self, request: Request) -> Response:
        repo = request.match_info["repo"]
        tag = request.match_info["tag"]
        accept = request.headers.get("Accept", "")
        self.accept_headers.append(accept)
        digest, media_type = self.tags[repo][tag]
        if tag in self.missing_tags or media_type not in accept:
            return json_response({"errors": [{"code": "MANIFEST_UNKNOWN"}]}, status=404)
        return json_response(
            {"mediaType": media_type},
            headers={"Docker-Content-Digest": digest},
            content_type=media_type,
        )

    async def handle_delete(self, request: Request) -> Response:
        digest = request.match_info["digest"]
        if digest in self.broken_digests:
            return json_response({"errors": [{"code": "UNKNOWN"}]}, status=500)
        self.deleted.append((request.match_info["repo"], digest))
        return Response(status=202)


class TestDeleteProjectImages:
    @pytest.fixture
    def registry(self) -> _Registry:
        return _Registry()

    @pytest.fixture
    async def client(
        self, aiohttp_server: _TestServerFactory, registry: _Registry
    ) -> AsyncIterator[UpstreamV2ApiClient]:
        app = Application()
        registry.register(app)
        server = await aiohttp_server(app)
        config = UpstreamRegistryConfig(
            type=UpstreamType.BASIC,
            endpoint_url=server.make_url(""),
            project="testproject",
            basic_username="testuser",
            basic_password="testpassword",
        )
        async with UpstreamV2ApiClient(config=config) as client:
            yield client

    async def test_image_digest_accepts_all_manifest_types(
        self, client: UpstreamV2ApiClient, registry: _Registry
    ) -> None:
        digest = await client.image_digest("org/project/index", "v1")

        assert digest == "sha256:index"
        accepted = {t.strip() for t in registry.accept_headers[0].split(",")}
        assert accepted == {
            OCI_INDEX,
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
            "application/vnd.docker.distribution.manifest.v2+json",
        }

    async def test_continues_past_failures_then_raises(
        self, client: UpstreamV2ApiClient, registry: _Registry
    ) -> None:
        with pytest.raises(ProjectImagesDeleteError) as exc_info:
            await client.delete_project_images(org="org", project="project")

        assert sorted(registry.deleted) == [
            ("testproject/org/project/alpine", "sha256:alpine"),
            ("testproject/org/project/index", "sha256:index"),
        ]
        assert str(exc_info.value) == (
            "Failed to delete images of org/project, 3 failed: org/project/broken, "
            "org/project/alpine:gone, org/project/alpine@sha256:bad"
        )

    async def test_no_error_when_all_deleted(
        self, client: UpstreamV2ApiClient, registry: _Registry
    ) -> None:
        del registry.tags["testproject/org/project/broken"]
        del registry.tags["testproject/org/project/alpine"]["bad"]
        del registry.tags["testproject/org/project/alpine"]["gone"]

        await client.delete_project_images(org="org", project="project")

        assert sorted(registry.deleted) == [
            ("testproject/org/project/alpine", "sha256:alpine"),
            ("testproject/org/project/index", "sha256:index"),
        ]

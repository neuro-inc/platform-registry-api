import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack
from importlib.metadata import version
from types import SimpleNamespace
from typing import Any

import aiohttp.web
import aiohttp_remotes
from aiohttp import ClientSession
from aiohttp.hdrs import (
    METH_DELETE,
    METH_GET,
    METH_PATCH,
    METH_POST,
    METH_PUT,
)
from aiohttp.web import (
    AppKey,
    Application,
    HTTPBadRequest,
    HTTPForbidden,
    HTTPUnauthorized,
    Request,
    Response,
    StreamResponse,
    json_response,
)
from aiohttp_security import check_authorized, check_permission
from neuro_admin_client import AdminClient, ProjectUser, User as AdminUser
from neuro_auth_client import AuthClient, Permission, User
from neuro_auth_client.security import AuthScheme, setup_security
from neuro_logging import (
    init_logging,
    setup_sentry,
    trace,
)
from pydantic import BaseModel, ConfigDict, ValidationError

from platform_registry_api.project_deleter import ProjectDeleter

from .config import (
    Config,
    EnvironConfigFactory,
)
from .upstream_client import UpstreamApiException, UpstreamV2ApiClient


logger = logging.getLogger(__name__)


V2_APP: AppKey[Application] = AppKey("v2_app")
UPSTREAM_CLIENT: AppKey[UpstreamV2ApiClient] = AppKey("upstream_client")
ADMIN: AppKey[AdminClient] = AppKey("admin")


class CatalogQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org: str | None = None
    project: str | None = None
    n: int | None = None
    last: str | None = None


class RootHandler:
    def register(self, app: aiohttp.web.Application) -> None:
        app.add_routes((aiohttp.web.get("/ping", self.handle_ping),))

    async def handle_ping(self, request: Request) -> Response:
        return Response(text="pong")


class V2Handler:
    def __init__(self, app: Application, config: Config) -> None:
        self._app = app
        self._config = config
        self._upstream_registry_config = config.upstream_registry

    @property
    def _upstream_client(self) -> UpstreamV2ApiClient:
        return self._app[UPSTREAM_CLIENT]

    @property
    def _admin(self) -> AdminClient:
        return self._app[ADMIN]

    def register(self, app: aiohttp.web.Application) -> None:
        app.add_routes(
            (
                aiohttp.web.get("/", self.handle_version_check),
                aiohttp.web.get("/_catalog", self.handle_catalog),
                aiohttp.web.get(r"/{repo:.+}/tags/list", self.handle_repo_tags_list),
            )
        )
        app.add_routes(
            aiohttp.web.route(
                method,
                r"/{repo:.+}/{path_suffix:(tags|manifests|blobs)/.*}",
                self.handle,
            )
            for method in (
                # METH_HEAD,
                METH_GET,
                METH_POST,
                METH_DELETE,
                METH_PATCH,
                METH_PUT,
            )
        )

    async def _get_user_from_request(self, request: Request) -> User:
        try:
            user_name = await check_authorized(request)
        except ValueError as exc:
            raise HTTPBadRequest() from exc
        except HTTPUnauthorized:
            self._raise_unauthorized()
        return User(name=user_name)

    def _raise_unauthorized(self) -> None:
        raise HTTPUnauthorized(
            headers={"WWW-Authenticate": f'Basic realm="{self._config.server.name}"'}
        )

    def _upstream_exc_to_response(self, exception: UpstreamApiException) -> Response:
        try:
            json_data = json.loads(exception.message)
            return json_response(status=exception.code, data=json_data)
        except json.JSONDecodeError:
            return Response(status=exception.code, text=exception.message)

    async def handle_version_check(self, request: Request) -> Response:
        await self._get_user_from_request(request)
        try:
            v2_result = await self._upstream_client.v2()
            return json_response(v2_result)
        except UpstreamApiException as e:
            return self._upstream_exc_to_response(e)

    async def handle_catalog(self, request: Request) -> Response:  # noqa: C901
        try:
            params = CatalogQueryParams(**dict(request.query))  # type: ignore[arg-type]
        except ValidationError as e:
            raise HTTPBadRequest(text=e.json()) from e

        user = await self._get_user_from_request(request)
        user_response: tuple[AdminUser, list[ProjectUser]] = await self._admin.get_user(
            user.name, include_projects=True
        )

        org_project_filters = [
            f"{project.org_name}/{project.project_name}"
            for project in user_response[1]
            if (params.org is None or project.org_name == params.org)
            and (params.project is None or project.project_name == params.project)
        ]

        # NOTE: we don't need to check permissions, cause admin.get_user
        # already return projects with at least reader permission

        try:
            repositories = [
                repo
                async for repo in self._upstream_client.list_images(
                    org_project_filters=org_project_filters,
                    n=params.n,
                    last=params.last,
                )
            ]
            return json_response(data={"repositories": repositories})
        except UpstreamApiException as e:
            return self._upstream_exc_to_response(e)

    async def handle_repo_tags_list(self, request: Request) -> Response:
        await self._get_user_from_request(request)
        repo = request.match_info["repo"]

        permission = Permission(
            uri=f"image://{self._config.cluster_name}/{repo}",
            action="read",
        )
        await self._check_user_permissions(request, [permission])

        try:
            tags = await self._upstream_client.image_tags_list(repo=repo)
            return json_response(data={"name": repo, "tags": tags})
        except UpstreamApiException as e:
            return self._upstream_exc_to_response(e)

    async def handle(self, request: Request) -> StreamResponse:
        await self._get_user_from_request(request)
        repo = request.match_info["repo"]
        path_suffix = request.match_info["path_suffix"]

        registry_repo = self._upstream_client._registry_repo_name(repo)
        permissions = [
            Permission(
                uri=f"image://{self._config.cluster_name}/{registry_repo}",
                action="read" if self._is_pull_request(request) else "write",
            )
        ]
        if "blobs/uploads" in path_suffix:
            if mounted_repo := request.query.get("from"):
                registry_mounted_repo = self._upstream_client._registry_repo_name(
                    mounted_repo
                )
                permissions.append(
                    Permission(
                        uri=f"image://{self._config.cluster_name}/{registry_mounted_repo}",
                        action="read",
                    )
                )

        await self._check_user_permissions(request, permissions)
        try:
            return await self._upstream_client.proxy_request(request)
        except UpstreamApiException as e:
            return self._upstream_exc_to_response(e)

    def _is_pull_request(self, request: Request) -> bool:
        return request.method in ("HEAD", "GET")

    @trace
    async def _check_user_permissions(
        self, request: Request, permissions: Sequence[Permission]
    ) -> None:
        assert self._config.cluster_name
        logger.info("Checking %s", permissions)
        try:
            await check_permission(request, "ignored", permissions)
        except HTTPUnauthorized:
            self._raise_unauthorized()


package_version = version("platform-registry-api")


async def add_version_to_header(request: Request, response: StreamResponse) -> None:
    response.headers["X-Service-Version"] = f"platform-registry-api/{package_version}"


async def create_app(config: Config) -> aiohttp.web.Application:
    app = aiohttp.web.Application()

    await aiohttp_remotes.setup(app, aiohttp_remotes.XForwardedRelaxed())

    async def _init_app(app: aiohttp.web.Application) -> AsyncIterator[None]:
        async with AsyncExitStack() as exit_stack:

            async def on_request_redirect(
                session: ClientSession, ctx: SimpleNamespace, params: Any
            ) -> None:
                logger.debug("upstream redirect response: %s", params.response)

            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_redirect.append(on_request_redirect)

            logger.info("Initializing Registry Client Session")

            auth_client = await exit_stack.enter_async_context(
                AuthClient(
                    url=config.auth.server_endpoint_url,
                    token=config.auth.service_token,
                )
            )

            await setup_security(
                app=app, auth_client=auth_client, auth_scheme=AuthScheme.BASIC
            )

            upstream_client = await exit_stack.enter_async_context(
                UpstreamV2ApiClient(config=config.upstream_registry)
            )

            app[V2_APP][UPSTREAM_CLIENT] = upstream_client

            admin = await exit_stack.enter_async_context(
                AdminClient(
                    base_url=config.admin.endpoint_url,
                    service_token=config.admin.token,
                )
            )
            app[V2_APP][ADMIN] = admin

            await exit_stack.enter_async_context(
                ProjectDeleter(upstream_client, config.events)
            )

            yield

    app.cleanup_ctx.append(_init_app)

    root_handler = RootHandler()
    root_handler.register(app)

    v2_app = aiohttp.web.Application()
    v2_handler = V2Handler(app=v2_app, config=config)
    v2_handler.register(v2_app)

    app[V2_APP] = v2_app

    app.add_subapp("/v2", v2_app)

    app.on_response_prepare.append(add_version_to_header)

    return app


def main() -> None:
    init_logging()

    loop = asyncio.get_event_loop()

    config = EnvironConfigFactory().create()
    logger.info("Loaded config: %r", config)
    setup_sentry(ignore_errors=[HTTPUnauthorized, HTTPForbidden])
    app = loop.run_until_complete(create_app(config))
    aiohttp.web.run_app(app, host=config.server.host, port=config.server.port)


if __name__ == "__main__":
    main()

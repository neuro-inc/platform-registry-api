import pytest
from yarl import URL

from platform_registry_api.api import RegistryRepoURL, URLFactory


class TestRegistryRepoURL:
    @pytest.mark.parametrize('url', (
        URL('/'),
        URL('/v2/'),
        URL('/v2/tags/list'),
        URL('/v2/blobs/uploads/'),
    ))
    def test_from_url_value_error(self, url):
        with pytest.raises(
                ValueError, match=f'unexpected path in a registry URL: {url}'):
            RegistryRepoURL.from_url(url)

    def test_from_url(self):
        url = URL('https://example.com/v2/name/tags/list?whatever=thatis')
        reg_url = RegistryRepoURL.from_url(url)
        assert reg_url == RegistryRepoURL(repo='name', url=url)

    def test_from_url_edge_case_1(self):
        url = URL('/v2/tags/tags/list?whatever=thatis')
        reg_url = RegistryRepoURL.from_url(url)
        assert reg_url == RegistryRepoURL(repo='tags', url=url)

    def test_from_url_edge_case_2(self):
        url = URL('/v2/tags/tags/tags/list?whatever=thatis')
        reg_url = RegistryRepoURL.from_url(url)
        assert reg_url == RegistryRepoURL(repo='tags/tags', url=url)

    def test_with_repo(self):
        url = URL('https://example.com/v2/this/image/tags/list?what=ever')
        reg_url = RegistryRepoURL.from_url(url).with_repo('another/img')
        assert reg_url == RegistryRepoURL(repo='another/img', url=URL(
            'https://example.com/v2/another/img/tags/list?what=ever'))

    def test_with_origin(self):
        url = URL('https://example.com/v2/this/image/tags/list?what=ever')
        reg_url = RegistryRepoURL.from_url(url).with_origin(URL('http://a.b'))
        assert reg_url == RegistryRepoURL(repo='this/image', url=URL(
            'http://a.b/v2/this/image/tags/list?what=ever'))


class TestURLFactory:
    @pytest.fixture
    def url_factory(self):
        registry_endpoint_url = URL('http://registry:5000')
        upstream_endpoint_url = URL('http://upstream:5000')
        return URLFactory(
            registry_endpoint_url=registry_endpoint_url,
            upstream_endpoint_url=upstream_endpoint_url,
            upstream_project='upstream',
        )

    def test_create_registry_version_check_url(self, url_factory):
        assert url_factory.create_registry_version_check_url() == URL(
            'http://upstream:5000/v2/')

    def test_create_upstream_repo_url(self, url_factory):
        reg_repo_url = RegistryRepoURL.from_url(URL(
            'http://registry:5000/v2/this/image/tags/list?what=ever'))
        up_repo_url = url_factory.create_upstream_repo_url(reg_repo_url)

        expected_url = URL(
            'http://upstream:5000/v2/upstream/this/image/tags/list?what=ever')
        assert up_repo_url == RegistryRepoURL(
            repo='upstream/this/image', url=expected_url)

    def test_create_registry_repo_url(self, url_factory):
        up_repo_url = RegistryRepoURL.from_url(URL(
            'http://upstream:5000/v2/upstream/this/image/tags/list?what='))
        reg_repo_url = url_factory.create_registry_repo_url(up_repo_url)

        expected_url = URL(
            'http://registry:5000/v2/this/image/tags/list?what=')
        assert reg_repo_url == RegistryRepoURL(
            repo='this/image', url=expected_url)

    def test_create_registry_repo_url_no_project(self, url_factory):
        up_repo_url = RegistryRepoURL.from_url(URL(
            'http://upstream:5000/v2/image/tags/list?what='))
        with pytest.raises(
                ValueError, match='Upstream project "" does not match'):
            url_factory.create_registry_repo_url(up_repo_url)

    def test_create_registry_repo_url_wrong_project(self, url_factory):
        up_repo_url = RegistryRepoURL.from_url(URL(
            'http://upstream:5000/v2/unknown/image/tags/list?what='))
        with pytest.raises(
                ValueError, match='Upstream project "unknown" does not match'):
            url_factory.create_registry_repo_url(up_repo_url)

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

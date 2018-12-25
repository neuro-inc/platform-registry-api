import pytest
from yarl import URL

from platform_registry_api.api import RepoURL, URLFactory, V2Handler


class TestRepoURL:
    @pytest.mark.parametrize('url', (
        URL('/'),
        URL('/v2/'),
        URL('/v2/tags/list'),
        URL('/v2/blobs/uploads/'),
    ))
    def test_from_url_value_error(self, url):
        with pytest.raises(
                ValueError, match=f'unexpected path in a registry URL: {url}'):
            RepoURL.from_url(url)

    def test_from_url(self):
        url = URL('https://example.com/v2/name/tags/list?whatever=thatis')
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo='name', url=url)

    def test_from_url_edge_case_1(self):
        url = URL('/v2/tags/tags/list?whatever=thatis')
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo='tags', url=url)

    def test_from_url_edge_case_2(self):
        url = URL('/v2/tags/tags/tags/list?whatever=thatis')
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo='tags/tags', url=url)

    def test_with_repo(self):
        url = URL('https://example.com/v2/this/image/tags/list?what=ever')
        reg_url = RepoURL.from_url(url).with_repo('another/img')
        assert reg_url == RepoURL(repo='another/img', url=URL(
            'https://example.com/v2/another/img/tags/list?what=ever'))

    def test_with_origin(self):
        url = URL('https://example.com/v2/this/image/tags/list?what=ever')
        reg_url = RepoURL.from_url(url).with_origin(URL('http://a.b'))
        assert reg_url == RepoURL(repo='this/image', url=URL(
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
        reg_repo_url = RepoURL.from_url(URL(
            'http://registry:5000/v2/this/image/tags/list?what=ever'))
        up_repo_url = url_factory.create_upstream_repo_url(reg_repo_url)

        expected_url = URL(
            'http://upstream:5000/v2/upstream/this/image/tags/list?what=ever')
        assert up_repo_url == RepoURL(
            repo='upstream/this/image', url=expected_url)

    def test_create_registry_repo_url(self, url_factory):
        up_repo_url = RepoURL.from_url(URL(
            'http://upstream:5000/v2/upstream/this/image/tags/list?what='))
        reg_repo_url = url_factory.create_registry_repo_url(up_repo_url)

        expected_url = URL(
            'http://registry:5000/v2/this/image/tags/list?what=')
        assert reg_repo_url == RepoURL(repo='this/image', url=expected_url)

    def test_create_registry_repo_url_no_project(self, url_factory):
        up_repo_url = RepoURL.from_url(URL(
            'http://upstream:5000/v2/image/tags/list?what='))
        with pytest.raises(
                ValueError, match='Upstream project "" does not match'):
            url_factory.create_registry_repo_url(up_repo_url)

    def test_create_registry_repo_url_wrong_project(self, url_factory):
        up_repo_url = RepoURL.from_url(URL(
            'http://upstream:5000/v2/unknown/image/tags/list?what='))
        with pytest.raises(
                ValueError, match='Upstream project "unknown" does not match'):
            url_factory.create_registry_repo_url(up_repo_url)


class TestV2Handler:

    def test_filter_images__empty(self):
        images = []
        expected = V2Handler._filter_images(images, 'repo')
        assert expected == []

    def test_filter_images__none(self):
        images = None
        expected = V2Handler._filter_images(images, 'repo')
        assert expected == []

    def test_filter_images__short_repository_name(self):
        images = ['repo/image1:good', 'repo/image2:good', 'repo99/image3:bad']
        expected = V2Handler._filter_images(images, 'repo')
        assert expected == ['repo/image1:good', 'repo/image2:good']

    def test_filter_images__wrong_repository_name(self):
        images = ['repository/image_1:bad', 'rep/img_2:bad', 'repo/img_3:bad']
        expected = V2Handler._filter_images(images, 'abrakadabra')
        assert expected == []

    def test_filter_images__empty_repository_name(self):
        images = ['repository/image_1:bad', 'rep/img_2:bad', 'repo/img_3:bad']
        with pytest.raises(ValueError, match='Empty repository name'):
            V2Handler._filter_images(images, '')
            V2Handler._filter_images(images, None)

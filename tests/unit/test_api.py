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
                ValueError, match='Upstream project '' does not match'):
            url_factory.create_registry_repo_url(up_repo_url)

    def test_create_registry_repo_url_wrong_project(self, url_factory):
        up_repo_url = RepoURL.from_url(URL(
            'http://upstream:5000/v2/unknown/image/tags/list?what='))
        with pytest.raises(
                ValueError, match="Upstream project 'unknown' does not match"):
            url_factory.create_registry_repo_url(up_repo_url)


class TestV2Handler:
    _filter = V2Handler._filter_images_by_repository

    def test__filter_images__empty_input(self):
        images = []
        expected = self._filter('project', 'repository', images)
        assert expected == []

    def test__filter_images__by_project_name(self):
        images = [
            'project1/repository/image1:bad',
            'project/repository/image2:good',
            'proj/repository/image3:bad',
            'abrakadabra/repository/image4:bad',
        ]
        expected = self._filter('project', 'repository', images)
        assert expected == ['project/repository/image2:good']

    def test__filter_images__by_repository_name(self):
        images = [
            'project/repository1/image1:bad',
            'project/repository/image2:good',
            'project/repo/image3:bad',
            'project/abrakadabra/image4:bad',
        ]
        expected = self._filter('project', 'repository', images)
        assert expected == ['project/repository/image2:good']

    def test__filter_images__none_or_empty_project_name(self):
        images = [
            'project1/repository/image1:bad',
            'project/repository/image2:bad',
            'proj/repository/image3:bad',
            'abrakadabra/repository/image4:bad',
        ]
        with pytest.raises(ValueError, match='Empty project name'):
            self._filter(None, 'repository', images)
            self._filter('', 'repository', images)

    def test__filter_images__none_or_empty_repository_name(self):
        images = [
            'project/project1/image1:bad',
            'project/project/image2:bad',
            'project/proj/image3:bad',
            'project/abrakadabra/image4:bad',
        ]
        with pytest.raises(ValueError, match='Empty repository name'):
            self._filter('project', None, images)
            self._filter('project', '', images)

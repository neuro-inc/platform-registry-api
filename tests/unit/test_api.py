import pytest
from neuro_auth_client.client import ClientSubTreeViewRoot
from yarl import URL

from platform_registry_api.api import (
    DockerImage, RepoURL, URLFactory, V2Handler
)


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


class TestDockerImage:
    def test_parse__zero_slashes__fail(self):
        image = 'img:latest'
        with pytest.raises(ValueError,
                           match='must contain two slashes'):
            DockerImage.parse(image)

    def test_parse__one_slash__fail(self):
        image = 'repository/ubuntu:latest'
        with pytest.raises(ValueError,
                           match='must contain two slashes'):
            DockerImage.parse(image)

    def test_parse__two_slashes(self):
        image = 'testproject/repository/ubuntu:latest'
        actual = DockerImage.parse(image)
        assert actual == DockerImage(
            project='testproject',
            repository='repository',
            name='ubuntu',
            tag='latest'
        )

    def test_parse__three_slashes__fail(self):
        image = 'testproject/repository/nothing/ubuntu:latest'
        with pytest.raises(ValueError,
                           match='must contain two slashes'):
            DockerImage.parse(image)

    def test_parse__many_slashes__fail(self):
        image = 'testproject/repository/image/name/with/many//slashes:latest'
        with pytest.raises(ValueError,
                           match='must contain two slashes'):
            DockerImage.parse(image)

    def test_parse__many_colons_in_image_name__fail(self):
        image = 'testproject/repository/ubuntu:latest:latest2'
        with pytest.raises(ValueError, match='must contain zero or one colon'):
            DockerImage.parse(image)

    def test_parse__no_colons(self):
        image = 'testproject/user-name/ubuntu'
        actual = DockerImage.parse(image)
        assert actual == DockerImage(
            project='testproject',
            repository='user-name',
            name='ubuntu',
            tag='latest'
        )

    def test_parse(self):
        image = 'testproject/user-name/ubuntu:latest'
        actual = DockerImage.parse(image)
        assert actual == DockerImage(
            project='testproject',
            repository='user-name',
            name='ubuntu',
            tag='latest'
        )

    def test_docker_image_to_url(self):
        image = 'testproject/user-name/ubuntu:latest'
        actual = DockerImage.parse(image)
        assert str(actual.to_url()) == 'image://user-name/ubuntu:latest'


class TestV2HandlerCheckImageAccess:

    def test_default_permissions(self):
        image = DockerImage(project='testproject', repository='testuser',
                            name='img', tag='latest')
        tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'testuser': {
                    'action': 'manage',
                    'children': {}
                }
            },
            'path': '/'
        })
        assert V2Handler.check_image_access(image, tree) is True

    def test_explicit_list_permissions(self):
        image = DockerImage(project='testproject', repository='testuser',
                            name='img', tag='latest')
        tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'testuser': {
                    'action': 'list',
                    'children': {
                        'img:latest': {
                            'action': 'list',
                            'children': {}
                        }
                    }
                }
            },
            'path': '/'
        })
        assert V2Handler.check_image_access(image, tree) is True

    def test_explicit_read_permissions(self):
        image = DockerImage(project='testproject', repository='testuser',
                            name='img', tag='latest')
        tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'testuser': {
                    'action': 'list',
                    'children': {
                        'img:latest': {
                            'action': 'read',
                            'children': {}
                        }
                    }
                }
            },
            'path': '/'
        })
        assert V2Handler.check_image_access(image, tree) is True

    def test_explicit_manage_permissions(self):
        image = DockerImage(project='testproject', repository='testuser',
                            name='img', tag='latest')
        tree = ClientSubTreeViewRoot._from_json({
            'action': 'deny',
            'children': {
                'testuser': {
                    'action': 'list',
                    'children': {
                        'img:latest': {
                            'action': 'manage',
                            'children': {}
                        }
                    }
                }
            },
            'path': '/'
        })
        assert V2Handler.check_image_access(image, tree) is True

    def test_default_permissions_but_different_user(self):
        image = DockerImage(project='testproject', repository='testuser',
                            name='img', tag='latest')
        tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'anothertestuser': {
                    'action': 'manage',
                    'children': {}
                }
            },
            'path': '/'
        })
        assert V2Handler.check_image_access(image, tree) is False

    def test_shared_image(self):
        image = DockerImage(project='testproject',
                            repository='anothertestuser',
                            name='img', tag='latest')
        tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'testuser': {
                    'action': 'manage',
                    'children': {}
                },
                'anothertestuser': {
                    'action': 'read',
                    'children': {
                        'img:latest': {
                            'action': 'manage',
                            'children': {}
                        }
                    }
                }
            },
            'path': '/'
        })
        assert V2Handler.check_image_access(image, tree) is True

    def test_filter_images__no_elements(self):
        images = []
        default_tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'testuser': {
                    'action': 'manage',
                    'children': {}
                }
            },
            'path': '/'
        })
        project_name = 'testproject'
        assert (
            list(V2Handler.filter_images(images, default_tree, project_name))
            == []
        )

    def test_filter_images__by_project_name(self):
        images = [
            DockerImage(project='testproject', repository='testuser',
                        name='img1', tag='latest'),
            DockerImage(project='anotherproject', repository='testuser',
                        name='img2', tag='latest')
        ]
        default_tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'testuser': {
                    'action': 'manage',
                    'children': {}
                }
            },
            'path': '/'
        })
        project_name = 'testproject'
        assert (
            list(V2Handler.filter_images(images, default_tree, project_name))
            ==
            [
                DockerImage(project='testproject', repository='testuser',
                            name='img1', tag='latest')
            ]
        )

    def test_filter_images__by_access_tree(self):
        images = [
            DockerImage(project='testproject', repository='testuser',
                        name='img1', tag='latest'),
            DockerImage(project='testproject', repository='testuser',
                        name='img2', tag='latest')
        ]
        tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'testuser': {
                    'action': 'list',
                    'children': {
                        'img1:latest': {
                            'action': 'list',
                            'children': {}
                        }
                    }
                }
            },
            'path': '/'
        })
        project_name = 'testproject'
        assert list(V2Handler.filter_images(images, tree, project_name)) == [
            DockerImage(project='testproject', repository='testuser',
                        name='img1', tag='latest')
        ]

    def test_filter_images__project_name_and_access_tree(self):
        images = [
            DockerImage(project='testproject', repository='testuser',
                        name='img1', tag='latest'),
            DockerImage(project='testproject', repository='testuser',
                        name='img2', tag='latest'),
            DockerImage(project='anotherproject', repository='testuser',
                        name='img3', tag='latest')
        ]
        tree = ClientSubTreeViewRoot._from_json({
            'action': 'list',
            'children': {
                'testuser': {
                    'action': 'list',
                    'children': {
                        'img1:latest': {
                            'action': 'list',
                            'children': {}
                        }
                    }
                }
            },
            'path': '/'
        })
        project_name = 'testproject'
        assert list(V2Handler.filter_images(images, tree, project_name)) == [
            DockerImage(project='testproject', repository='testuser',
                        name='img1', tag='latest')
        ]

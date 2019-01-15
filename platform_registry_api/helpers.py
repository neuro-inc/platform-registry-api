from neuro_auth_client.client import ClientSubTreeViewRoot


def check_image_catalog_permission(
        image_name_and_tag: str,
        tree: ClientSubTreeViewRoot
) -> bool:
    # The permission tree contains the tagged image name
    # for example, "username/image/name/with/slashes:tag"
    parts = image_name_and_tag.split('/')
    node = tree.sub_tree
    # colon ":" is allowed only at leafs (docker image name format)
    for part in parts:
        # if permission is not "list", we can make decision already
        if node.action != 'list':
            break
        child = node.children.get(part)
        if child is None:
            break
        node = node.children[part]
    return node.action not in {'deny', 'list'}

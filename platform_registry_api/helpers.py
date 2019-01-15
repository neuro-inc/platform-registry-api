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
        if node.action == 'list':
            # if permission is "list", try to go on deeper
            child = node.children.get(part)
            if child:
                node = node.children[part]
            else:
                prefix = part + ':'
                matching_leaves = [
                    leaf_value
                    for leaf_name, leaf_value in node.children.items()
                    if not leaf_value.children
                    and leaf_name.startswith(prefix)
                ]
                if not matching_leaves:
                    # ...then check the parent node only
                    break

                # check that nothing is forbidden
                return not any(
                    leaf.action in {'deny', 'list'}
                    for leaf in matching_leaves
                )
        else:
            # if permission >= "read", stop checking further
            break
    return node.action not in {'deny', 'list'}

from neuro_auth_client.client import ClientSubTreeViewRoot


def check_image_catalog_permission(
    image_name_and_tag: str, tree: ClientSubTreeViewRoot
) -> bool:
    parts = image_name_and_tag.split("/")
    node = tree.sub_tree
    for part in parts:
        # if permission is not "list", we can make decision already
        if node.action != "list":
            break
        child = node.children.get(part)
        if child is None:
            break
        node = node.children[part]
    return node.action not in {"deny", "list"}

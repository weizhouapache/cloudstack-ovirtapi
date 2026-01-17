from lxml.etree import Element, SubElement, tostring
from fastapi import Response

def api_root_full():
    payload = {
        "product_info": {
            "name": "CloudStack oVirtAPI Server",
            "vendor": "Wei Zhou",
            "version": "1.0"
        }
    }
    return xml_response("api", payload)


def _to_dict(obj):
    """
    Convert object → dict
    """
    if isinstance(obj, dict):
        return obj
    return {
        k: v for k, v in vars(obj).items()
    }


def _build_xml(parent: Element, data):
    """
    Recursively build XML from dict / list / object / scalar.
    """
    if data is None:
        return

    # list → repeated elements
    if isinstance(data, list):
        for item in data:
            child = SubElement(parent, parent.tag[:-1] if parent.tag.endswith("s") else "item")
            _build_xml(child, item)
        return

    # object or dict
    if isinstance(data, (dict, object)) and not isinstance(data, (str, int, float, bool)):
        data_dict = _to_dict(data)
        for key, value in data_dict.items():
            child = SubElement(parent, key)
            _build_xml(child, value)
        return

    # scalar
    parent.text = str(data)


def xml_response(root_name: str, payload, status_code: int = 200) -> Response:
    """
    Build XML response from object/dict/list.
    """
    root = Element(root_name)
    _build_xml(root, payload)

    return Response(
        content=tostring(root, encoding="utf-8", pretty_print=True),
        media_type="application/xml",
        status_code=status_code
    )


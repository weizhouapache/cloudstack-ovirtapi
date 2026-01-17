from lxml import etree

def api_root_full():
    root = etree.Element("api")
    pi = etree.SubElement(root, "product_info")
    etree.SubElement(pi, "name").text = "CloudStack oVirtAPI Server"
    etree.SubElement(pi, "vendor").text = "weizhouapache"
    etree.SubElement(pi, "version").text = "1.0"
    return etree.tostring(root, pretty_print=True)

def xml_response(root_tag: str, children: dict = None):
    root = etree.Element(root_tag)
    if children:
        for k, v in children.items():
            child = etree.SubElement(root, k)
            child.text = str(v)
    return etree.tostring(
        root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8"
    )

def vms_response(vms):
    root = etree.Element("vms")
    for vm in vms:
        e = etree.SubElement(root, "vm")
        etree.SubElement(e, "id").text = vm["id"]
        etree.SubElement(e, "name").text = vm["name"]
        etree.SubElement(e, "status").text = vm["state"]
    return etree.tostring(root, pretty_print=True)

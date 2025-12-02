import unittest
from unittest.mock import patch, Mock
import xml.etree.ElementTree as ET

from shared.challenge_builder import OscBuilder


def _mock_response(element):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"elements": [element]}
    return response


class OscBuilderTests(unittest.TestCase):
    def test_empty_builder_outputs_minimal_xml(self):
        builder = OscBuilder(generator="testgen")
        xml_str = builder.to_string()
        root = ET.fromstring(xml_str)
        self.assertEqual(root.tag, "osmChange")
        self.assertEqual(root.attrib["version"], "0.6")
        self.assertEqual(root.attrib["generator"], "testgen")
        self.assertEqual(len(list(root)), 0)

    @patch("shared.challenge_builder.requests.get")
    def test_remove_object_generates_delete_node(self, mock_get):
        mock_get.return_value = _mock_response({
            "type": "node",
            "id": 123,
            "version": 7,
            "lat": 1.23,
            "lon": 4.56,
            "tags": {"amenity": "cafe"}
        })
        builder = OscBuilder()
        xml_str = builder.removeObject("node", 123).to_string()
        root = ET.fromstring(xml_str)
        delete_nodes = root.find("delete").findall("node")
        self.assertEqual(len(delete_nodes), 1)
        node = delete_nodes[0]
        self.assertEqual(node.attrib["id"], "123")
        self.assertEqual(node.attrib["version"], "7")
        tags = node.findall("tag")
        self.assertEqual(tags[0].attrib, {"k": "amenity", "v": "cafe"})

    @patch("shared.challenge_builder.requests.get")
    def test_remove_node_from_way_rewrites_members(self, mock_get):
        mock_get.return_value = _mock_response({
            "type": "way",
            "id": 10,
            "version": 3,
            "nodes": [1, 2, 3],
            "tags": {}
        })
        builder = OscBuilder()
        xml_str = builder.removeNodeFromWay(10, 2).to_string()
        root = ET.fromstring(xml_str)
        modify_way = root.find("modify").find("way")
        nd_refs = [nd.attrib["ref"] for nd in modify_way.findall("nd")]
        self.assertEqual(nd_refs, ["1", "3"])

    @patch("shared.challenge_builder.requests.get")
    def test_add_object_to_relation_inserts_at_position(self, mock_get):
        mock_get.return_value = _mock_response({
            "type": "relation",
            "id": 55,
            "version": 2,
            "members": [
                {"type": "node", "ref": 1, "role": "stop"},
                {"type": "way", "ref": 2, "role": "route"}
            ],
            "tags": {}
        })
        builder = OscBuilder()
        xml_str = builder.addObjectToRelation(55, "node", 99, position=1, role="platform").to_string()
        root = ET.fromstring(xml_str)
        members = root.find("modify").find("relation").findall("member")
        ordered_refs = [(m.attrib["type"], m.attrib["ref"], m.attrib.get("role", "")) for m in members]
        self.assertEqual(
            ordered_refs,
            [("node", "1", "stop"), ("node", "99", "platform"), ("way", "2", "route")]
        )

    @patch("shared.challenge_builder.requests.get")
    def test_add_object_to_relation_negative_index(self, mock_get):
        mock_get.return_value = _mock_response({
            "type": "relation",
            "id": 77,
            "version": 1,
            "members": [
                {"type": "node", "ref": 1, "role": ""},
                {"type": "node", "ref": 2, "role": ""}
            ],
            "tags": {}
        })
        builder = OscBuilder()
        xml_str = builder.addObjectToRelation(77, "way", 5, position=-1, role="outer").to_string()
        members = ET.fromstring(xml_str).find("modify").find("relation").findall("member")
        ordered_refs = [(m.attrib["type"], m.attrib["ref"], m.attrib.get("role", "")) for m in members]
        self.assertEqual(
            ordered_refs,
            [("node", "1", ""), ("node", "2", ""), ("way", "5", "outer")]
        )

    def test_create_node_uses_negative_id_and_tags(self):
        builder = OscBuilder()
        node_id = builder.createNode(10.0, 20.0, {"amenity": "bench"})
        self.assertLess(node_id, 0)
        root = ET.fromstring(builder.to_string())
        node = root.find("create").find("node")
        self.assertEqual(node.attrib["id"], str(node_id))
        self.assertEqual(node.attrib["lat"], "10.0")
        self.assertEqual(node.attrib["lon"], "20.0")
        tags = node.findall("tag")
        self.assertEqual(tags[0].attrib, {"k": "amenity", "v": "bench"})

    def test_create_way_from_coordinates_creates_nodes_and_way(self):
        builder = OscBuilder()
        way_id, node_ids = builder.createWay([[1.0, 2.0], [3.0, 4.0]], tags={"highway": "service"})
        root = ET.fromstring(builder.to_string())
        create_section = root.find("create")
        elems = list(create_section)
        # First two are nodes, then the way
        self.assertEqual(elems[0].tag, "node")
        self.assertEqual(elems[1].tag, "node")
        way = elems[2]
        self.assertEqual(way.tag, "way")
        self.assertEqual(way.attrib["id"], str(way_id))
        nd_refs = [nd.attrib["ref"] for nd in way.findall("nd")]
        self.assertEqual(nd_refs, [str(node_ids[0]), str(node_ids[1])])
        tag = way.find("tag")
        self.assertEqual(tag.attrib, {"k": "highway", "v": "service"})


if __name__ == "__main__":
    unittest.main()

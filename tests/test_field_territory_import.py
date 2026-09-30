import json

import pytest

pytest.importorskip('shapely')
from shapely.geometry import Point, shape
from scripts.prepare_entomologia_territory import build


def test_import_keeps_holes_suffixes_and_original_coordinates_without_case_data(tmp_path):
    # The arithmetic center falls in a hole; the label must use real interior space.
    outer = '-47.89,-20.73 -47.88,-20.73 -47.88,-20.72 -47.89,-20.72 -47.89,-20.73'
    hole = '-47.887,-20.727 -47.883,-20.727 -47.883,-20.723 -47.887,-20.723 -47.887,-20.727'
    polygon = f'<Polygon><outerBoundaryIs><LinearRing><coordinates>{outer}</coordinates></LinearRing></outerBoundaryIs><innerBoundaryIs><LinearRing><coordinates>{hole}</coordinates></LinearRing></innerBoundaryIs></Polygon>'
    source = tmp_path / 'reference.kml'
    source.write_text(f'''<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>2026</name>
      <Folder><name>Casos Dengue</name><Placemark><name>PRIVATE-PATIENT</name><Point><coordinates>-47.8,-20.7</coordinates></Point></Placemark></Folder>
      <Folder><name>Quadras</name><Folder><name>Quadras e SCs</name><Folder><name>SETOR 2</name><Folder><name>SC 103</name>
      <Placemark id="block-a"><name>899A</name><description>PRIVATE-DESCRIPTION</description>{polygon}</Placemark>
      <Placemark id="block-b"><name>899B</name>{polygon}</Placemark>
      </Folder></Folder></Folder></Folder></Document></kml>''', encoding='utf-8')
    data = build(source)
    assert len(data['features']) == 2
    assert [f['properties']['block'] for f in data['features']] == ['899A', '899B']
    assert 'PRIVATE' not in json.dumps(data)
    for feature in data['features']:
        geometry = shape(feature['geometry'])
        assert geometry.covers(Point(feature['properties']['label']))
        assert feature['geometry']['coordinates'][0][0][0] == [-47.89, -20.73]
        assert len(feature['geometry']['coordinates'][0]) == 2


def test_import_rejects_xml_entities_instead_of_expanding_them(tmp_path):
    source = tmp_path / 'unsafe.kml'
    source.write_text('<!DOCTYPE kml [<!ENTITY private SYSTEM "file:///secret">]><kml/>', encoding='utf-8')
    with pytest.raises(ValueError, match='entities'):
        build(source)

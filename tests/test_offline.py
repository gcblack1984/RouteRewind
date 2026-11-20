import gzip
import os
import random
import sys
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from offline import OfflineLibrary, TileServer  # noqa: E402
from pmtiles_extract import (Extractor, Header, archive_info, read_tile, tileid_to_zxy,  # noqa: E402
                             tiles_in_bbox, write_archive, zxy_to_tileid)

PUGLIA = (16.9, 40.3, 18.6, 41.0)


def test_tileid_known_values():
    assert [zxy_to_tileid(0, 0, 0), zxy_to_tileid(1, 0, 0), zxy_to_tileid(1, 0, 1),
            zxy_to_tileid(1, 1, 1), zxy_to_tileid(1, 1, 0)] == [0, 1, 2, 3, 4]
    for _ in range(3000):
        z = random.randint(0, 16)
        x, y = random.randrange(1 << z), random.randrange(1 << z)
        assert tileid_to_zxy(zxy_to_tileid(z, x, y)) == (z, x, y)


def _blob(z, x, y):
    if z >= 6 and (x + y) % 5 == 0:
        return b"OCEAN"                 # contenuto ripetuto, come il mare nelle mappe vere
    return gzip.compress(f"{z}/{x}/{y}".encode(), mtime=0)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Archivio sintetico z0-8 (87.381 tessere) con directory foglia."""
    path = str(tmp_path_factory.mktemp("w") / "world.pmtiles")
    tiles = []
    for z in range(0, 9):
        for x in range(1 << z):
            for y in range(1 << z):
                tiles.append((zxy_to_tileid(z, x, y), _blob(z, x, y)))
    tiles.sort()
    hdr = Header(*([0] * 11), 1, 2, 2, 1, 0, 8, 0, 0, 0, 0, 0, 0, 0)
    write_archive(path, tiles, hdr, (-180, -85, 180, 85), 0, 8, b'{"name":"test"}')
    return path


def test_world_has_leaves(world):
    h = Header.parse(open(world, "rb").read(127))
    assert h.leaf_length > 0 and h.clustered == 1
    assert read_tile(world, 8, 137, 95) == _blob(8, 137, 95)


def _check_extract(out, bbox, maxzoom):
    ids = tiles_in_bbox(bbox, 0, maxzoom)
    for tid in ids:
        z, x, y = tileid_to_zxy(tid)
        assert read_tile(out, z, x, y) == _blob(z, x, y)
    assert read_tile(out, 8, 0, 0) is None
    info = archive_info(out)
    assert info["maxzoom"] == maxzoom and abs(info["bbox"][0] - bbox[0]) < 1e-6


def test_extract_local(world, tmp_path):
    out = str(tmp_path / "puglia.pmtiles")
    ex = Extractor(world, PUGLIA, maxzoom=8)
    plan = ex.plan()
    assert plan["tiles"] == len(tiles_in_bbox(PUGLIA, 0, 8))
    ex.run(out)
    _check_extract(out, PUGLIA, 8)


def test_extract_via_http_and_library(world, tmp_path):
    lib = OfflineLibrary(str(tmp_path / "lib"))
    imported = lib.import_file(world)
    srv = TileServer(lib.folder)
    try:
        url = srv.url_for(os.path.basename(imported))
        req = urllib.request.Request(url, headers={"Range": "bytes=0-6"})
        with urllib.request.urlopen(req) as r:
            assert r.status == 206 and r.read() == b"PMTiles"
            assert r.headers["Access-Control-Allow-Origin"] == "*"
        out = lib.new_path("Area percorso")
        Extractor(url, PUGLIA, maxzoom=7).run(out)
        lib.write_meta(out, "Area percorso")
        _check_extract(out, PUGLIA, 7)
        names = [m["name"] for m in lib.maps()]
        assert "Area percorso" in names
        lib.delete(out)
        assert "Area percorso" not in [m["name"] for m in lib.maps()]
    finally:
        srv.stop()

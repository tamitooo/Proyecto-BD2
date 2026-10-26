"""Demo corta para defensa: los índices sobreviven a un reinicio sin scan de tabla."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from query.catalog import Catalog
from storage.heap_file import HeapFile


def main():
    with TemporaryDirectory() as tmp:
        c = Catalog(data_dir=tmp)
        t = c.create_table(
            "demo",
            [("id","INT"),("score","FLOAT"),("lat","FLOAT"),("lon","FLOAT")],
            primary_key="id",
            primary_key_index=False,
        )
        for i in range(1, 11):
            t.storage.insert({"id":i,"score":float(i%3),"lat":-12-i/1000,"lon":-77-i/1000})
        c.create_index("demo","id",kind="hash",unique=True,name="idx_hash")
        c.create_index("demo","score",kind="bplus_unclustered",name="idx_bplus")
        c.create_index("demo","lat",lon_column="lon",kind="rtree",name="idx_rtree")

        print("Archivos persistentes:")
        for reg in c.get_table("demo").indexes.values():
            p=Path(reg.implementation.file_path)
            print(f"  {reg.metadata.name}: {p.name} ({p.stat().st_size} bytes)")

        definition=c.describe_tables()[0]
        reopened=Catalog(data_dir=tmp)
        with patch.object(HeapFile,"scan",side_effect=AssertionError("scan prohibido")):
            reopened.restore_table(definition,data_dir=tmp)

        print("\nReinicio sin scan: OK")
        print("Hash id=7 ->", reopened.get_index("demo","idx_hash").implementation.search(7))
        print("B+ score=1 ->", reopened.get_index("demo","idx_bplus").implementation.search(1.0))
        print("R-Tree entries ->", len(reopened.get_index("demo","idx_rtree").implementation))

if __name__ == "__main__":
    main()

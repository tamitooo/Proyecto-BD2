from tempfile import TemporaryDirectory
from backend.engine import DemoEngine


def main():
    with TemporaryDirectory() as directory:
        db=DemoEngine(directory)
        db.run("CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(30), lat FLOAT, lon FLOAT)")
        for row in [
            (1,'Centro',-12.0464,-77.0428),
            (2,'Norte',-12.0300,-77.0400),
            (3,'Sur',-12.1000,-77.0500),
            (4,'Este',-12.0500,-77.0000),
            (5,'Oeste',-12.0450,-77.0900),
        ]:
            db.run(f"INSERT INTO tiendas VALUES ({row[0]},'{row[1]}',{row[2]},{row[3]})")
        print(db.run("CREATE INDEX idx_geo ON tiendas (lat, lon) USING RTREE").to_dict())

        queries=[
            "SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464,-77.0428), HAVERSINE) < 5000",
            "SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464,-77.0428), EUCLIDEAN) < 0.05",
            "SET mi_ubicacion = POINT(-12.0464,-77.0428)",
            "SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion, HAVERSINE) LIMIT 3",
            "SELECT * FROM tiendas WHERE dentro_de(lat, POLYGON((-12.07 -77.10, -12.07 -76.98, -12.02 -76.98, -12.02 -77.10)))",
        ]
        for sql in queries:
            r=db.run(sql)
            print('\n>',sql,'\n',r.to_dict())


if __name__=='__main__':
    main()

from .csv_loader import infer_schema_from_csv,_coerce,CsvImportError
class TableManagementError(Exception):pass

def create_table(engine,*,name,columns,primary_key,storage_kind="heap",source="manual",original_filename=None):
    norm=[]
    for c in columns:
        if isinstance(c,dict):norm.append((c["name"].lower(),c["type"].upper()))
        else:norm.append((c[0].lower(),c[1].upper()))
    sql="CREATE TABLE %s (%s, PRIMARY KEY (%s)) USING %s"%(name.lower(),", ".join(f"{n} {t}" for n,t in norm),primary_key.lower(),storage_kind.upper())
    r=engine.run(sql)
    if not r.success:raise TableManagementError(r.error)
    engine._remember_source(name.lower(),source=source,filename=original_filename);return engine.table_info(name)

def import_csv_as_table(engine,*,name,filename,content,primary_key,storage_kind="heap",delimiter=",",encoding="utf-8"):
    text=content.decode(encoding) if isinstance(content,(bytes,bytearray)) else content
    try:schema=infer_schema_from_csv(text,primary_key=primary_key,delimiter=delimiter)
    except Exception as e:raise TableManagementError(str(e))
    create_table(engine,name=name,columns=schema,primary_key=primary_key,storage_kind=storage_kind,source="csv",original_filename=filename)
    try:rep=engine.import_csv(name,text,delimiter=delimiter)
    except Exception:
        engine.run(f"DROP TABLE IF EXISTS {name}");raise
    return {"imported_rows":rep.inserted,"table":engine.table_info(name),"inferred_schema":{"columnas":schema,"primary_key":primary_key},"original_filename":filename}

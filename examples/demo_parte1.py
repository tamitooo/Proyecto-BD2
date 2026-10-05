from tempfile import TemporaryDirectory
from backend.engine import DemoEngine


def main():
    with TemporaryDirectory() as directory:
        db=DemoEngine(directory)
        print('TABLAS:', [t['name'] for t in db.tables()])
        samples=[
            "SELECT * FROM users WHERE id = 2",
            "SELECT * FROM users WHERE age BETWEEN 19 AND 23 ORDER BY age",
            "SELECT dept, COUNT(*) AS total FROM employees GROUP BY dept ORDER BY dept",
            "SELECT users.name, employees.salary FROM users JOIN employees ON users.dept = employees.dept",
            "EXPLAIN ANALYZE SELECT * FROM employees WHERE salary >= 3900 ORDER BY salary",
        ]
        for sql in samples:
            r=db.run(sql)
            print('\n>',sql,'\n',r.to_dict())
        print('\nClustered físico users(age):', [row['age'] for _,row in db.catalog.get_table('users').storage.scan()])


if __name__=='__main__':
    main()

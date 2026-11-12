import pymysql

conn = pymysql.connect(
    host="192.168.10.120",
    port=3306,
    user="iflytek",
    password="123456",
    database="rag_cleaned",      # ← 换成你实际的库名
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)

with conn:
    with conn.cursor() as cur:
        cur.execute("show tables")
        for row in cur.fetchall():
            print(row)

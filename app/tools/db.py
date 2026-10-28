import psycopg2
from pymongo import MongoClient
from app.config.config import MONGODB_URI, SQL_URL

# Conexão do MongoDB
_mongo = MongoClient(MONGODB_URI)
db = _mongo["assessor"]
col_sessoes = db["sessoes"]

col_sessoes.create_index("session_id")
col_sessoes.create_index("iniciada_em")

# Conexão do PostgreSQL
def get_conn():
    return psycopg2.connect(SQL_URL)
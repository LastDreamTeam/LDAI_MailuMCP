"""Persistent OAuth state for a private connector. Secrets are hashed before lookup."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import closing


class Records:
    def __init__(self, db, namespace):
        self.db = db
        self.namespace = namespace
        with closing(self.open()) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS records (app TEXT, kind TEXT, k TEXT, body TEXT NOT NULL, expiry INTEGER NOT NULL, PRIMARY KEY(app,kind,k))")
            connection.commit()

    def open(self):
        return sqlite3.connect(self.db, timeout=10)

    @staticmethod
    def key(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def save(self, kind, value, body, ttl):
        with closing(self.open()) as connection, connection:
            now = int(time.time())
            connection.execute("DELETE FROM records WHERE expiry < ?", (now,))
            connection.execute("INSERT INTO records VALUES (?,?,?,?,?)", (self.namespace, kind, self.key(value), json.dumps(body), now + ttl))
        return value

    def issue(self, kind, body, ttl):
        return self.save(kind, secrets.token_urlsafe(36), body, ttl)

    def read(self, kind, value, consume=False):
        with closing(self.open()) as connection, connection:
            if consume:
                connection.execute("BEGIN IMMEDIATE")
            key = (self.namespace, kind, self.key(value))
            row = connection.execute("SELECT body FROM records WHERE app=? AND kind=? AND k=? AND expiry>=?", (*key, int(time.time()))).fetchone()
            if row and consume:
                connection.execute("DELETE FROM records WHERE app=? AND kind=? AND k=?", key)
            return json.loads(row[0]) if row else None

    def remove_grant(self, gid):
        with closing(self.open()) as connection, connection:
            connection.execute("DELETE FROM records WHERE app=? AND kind IN ('access','refresh') AND json_extract(body,'$.gid')=?", (self.namespace, gid))

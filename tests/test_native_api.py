# SPDX-License-Identifier: AGPL-3.0-only
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server

class NativeAPI(unittest.TestCase):
    def test_alias_uses_selected_token_and_reads_back(self):
        calls=[]
        mailbox="work@example.org"
        alias="alias@example.org"
        def exchange(var,path,body,headers):
            self.assertEqual(headers["Authorization"],"fixture")
            calls.append((path,body))
            if path=="/user":
                return json.dumps([{"email":mailbox}]).encode()
            if path=="/alias" and body is None:
                return b"[]"
            if body:
                self.assertEqual(json.loads(body)["destination"],[mailbox])
                return b""
            return json.dumps({"email":alias,"destination":[mailbox],"password":"hidden"}).encode()
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"credential"
            f.write_text("fixture",encoding="utf8")
            with patch.dict(os.environ,{"MAILU_API_TOKEN_FILE":str(f)}),patch.object(server,"request",exchange):
                result=server.mailu_create_alias(alias,[mailbox])
        self.assertEqual(len(calls),4)
        self.assertTrue(result["verified"])
        self.assertNotIn("password",result["alias"])

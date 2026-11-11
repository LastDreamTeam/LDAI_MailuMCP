# SPDX-License-Identifier: AGPL-3.0-only
import os,unittest,email
from unittest.mock import patch,MagicMock
import server
class Mail(unittest.TestCase):
    def test_smtp_envelope_cc_and_reply_headers(self):
        client=MagicMock();client.send_message.return_value={}
        with patch.dict(os.environ,{"MAILU_SMTP_HOST":"mail.example.org","MAILU_SMTP_USER":"work@example.org"}),patch.object(server,"secret",return_value="fixture"),patch.object(server.smtplib,"SMTP") as smtp:
            smtp.return_value.__enter__.return_value=client
            r=server.submit(["a@example.org"],["b@example.org"],"Re: original","reply","<id@example.org>","<id@example.org>")
            self.assertTrue(r["accepted_by_smtp"])
            msg=client.send_message.call_args.args[0]
            self.assertEqual(str(msg["Cc"]),"b@example.org")
            self.assertEqual(str(msg["In-Reply-To"]),"<id@example.org>")
            client.starttls.assert_called_once();client.login.assert_called_once()

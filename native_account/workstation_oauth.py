"""MCP OAuth with PKCE. Only the private workstation browser can approve a profile."""
import secrets
import time
from urllib.parse import urlencode, urlsplit

from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import AuthorizationCode, AuthorizeError, RefreshToken, RegistrationError, TokenError
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

SCOPE = "connector.read"
WEB_CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"


def callback_ok(uri):
    if uri == WEB_CALLBACK:
        return True
    try:
        port = urlsplit(uri).port
        return port and 1024 <= port <= 65535 and uri == f"http://127.0.0.1:{port}/callback"
    except ValueError:
        return False


class WorkstationOAuth(OAuthProvider):
    def __init__(self, origin, private_origin, store):
        self.origin = origin
        self.private_origin = private_origin
        self.store = store
        super().__init__(base_url=origin, required_scopes=[SCOPE],
                         client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
                         revocation_options=RevocationOptions(enabled=True))

    async def register_client(self, client_info):
        if not client_info.redirect_uris or not all(callback_ok(str(uri)) for uri in client_info.redirect_uris):
            raise RegistrationError("invalid_redirect_uri", "Use the registered OpenAI callback or a desktop loopback callback.")
        self.store.save("client", client_info.client_id, client_info.model_dump(mode="json",exclude_none=True), 365*86400)

    async def get_client(self, client_id):
        record = self.store.read("client", client_id)
        return OAuthClientInformationFull(**record) if record else None

    async def authorize(self, client, params):
        callback = str(params.redirect_uri)
        if callback not in [str(uri) for uri in client.redirect_uris] or not callback_ok(callback) or not params.code_challenge:
            raise AuthorizeError("invalid_request", "Client callback or PKCE is invalid.")
        resource = self.origin + "/mcp"
        if params.resource and str(params.resource).split("?",1)[0] != resource:
            raise AuthorizeError("invalid_request","Invalid resource.")
        if set(params.scopes or [SCOPE]) != {SCOPE}:
            raise AuthorizeError("invalid_scope","Invalid scope.")
        data = params.model_dump(mode="json")
        data.update(client_id=client.client_id, resource=resource, scopes=[SCOPE])
        ticket = self.store.issue("request",data,600)
        return self.private_origin + "/choose?" + urlencode({"app":self.store.namespace,"request":ticket})

    def approve(self, ticket, profile):
        request = self.store.read("request",ticket,consume=True)
        if not request:
            raise ValueError("This login request has expired.")
        request.update(profile)
        code = self.store.issue("code",request,90)
        values = {"code":code,"iss":self.origin}
        if request.get("state"):
            values["state"] = request["state"]
        return request["redirect_uri"]+"?"+urlencode(values)

    async def load_authorization_code(self, client, authorization_code):
        row=self.store.read("code",authorization_code)
        if row and row["client_id"]==client.client_id:
            return AuthorizationCode(code=authorization_code,scopes=[SCOPE],expires_at=time.time()+60,client_id=client.client_id,
                code_challenge=row["code_challenge"],redirect_uri=row["redirect_uri"],redirect_uri_provided_explicitly=row["redirect_uri_provided_explicitly"],
                resource=row["resource"],subject=row["id"])
        return None

    def issue_pair(self, row):
        access=self.store.issue("access",row,3600)
        refresh=self.store.issue("refresh",row,90*86400)
        return OAuthToken(access_token=access,refresh_token=refresh,scope=SCOPE,expires_in=3600)

    async def exchange_authorization_code(self,client,authorization_code):
        row=self.store.read("code",authorization_code.code,consume=True)
        if not row or row["client_id"]!=client.client_id:
            raise TokenError("invalid_grant","Authorization code has expired.")
        grant={k:row[k] for k in ("client_id","id","alias","fingerprint","resource")}
        grant["gid"]=secrets.token_urlsafe(24)
        return self.issue_pair(grant)

    async def load_refresh_token(self,client,refresh_token):
        row=self.store.read("refresh",refresh_token)
        if row and row["client_id"]==client.client_id:
            return RefreshToken(token=refresh_token,client_id=client.client_id,scopes=[SCOPE],resource=row["resource"],subject=row["id"])
        return None

    async def exchange_refresh_token(self,client,refresh_token,scopes):
        row=self.store.read("refresh",refresh_token.token,consume=True)
        if not row or row["client_id"]!=client.client_id or set(scopes)-{SCOPE}:
            raise TokenError("invalid_grant","Refresh grant expired.")
        return self.issue_pair(row)

    async def load_access_token(self,token):
        row=self.store.read("access",token)
        if row:
            return AccessToken(token=token,client_id=row["client_id"],resource=row["resource"],scopes=[SCOPE],subject=row["id"],claims=row)
        return None

    async def revoke_token(self,token):
        row = self.store.read("access",token.token) or self.store.read("refresh",token.token)
        if row:self.store.remove_grant(row["gid"])

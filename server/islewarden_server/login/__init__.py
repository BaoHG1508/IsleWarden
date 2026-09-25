"""Player login: Steam proves which Steam ID the player owns, Discord proves they are in the server's guild with a
required role, and the launcher receives a device key.

Native-app OAuth pattern (RFC 8252 loopback + PKCE), the same as the C# server:
  1. The launcher listens on 127.0.0.1:<port> and opens <server>/login/start?port=&state=&challenge= in the browser.
  2. Browser: Steam OpenID, then Discord OAuth2, then a redirect to http://127.0.0.1:<port>/callback?code=&state=
  3. The launcher POSTs /api/login/complete with that code and its PKCE verifier and gets a device key.
The final redirect only reaches a listener on the machine whose browser signed in, and only the launcher that
started the flow knows the verifier, so a login link sent to someone else can't hijack their account.
"""

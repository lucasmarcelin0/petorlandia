#!/bin/sh
# Git credential helper for git.heroku.com that reads the token from the
# already-authenticated Heroku CLI session (heroku login), instead of
# relying on Windows Git Credential Manager (which rejects Heroku's
# username/password auth) or a manually pasted token.
#
# Configured locally via:
#   git config --local credential."https://git.heroku.com".helper \
#     "!sh scripts/heroku_git_credential_helper.sh"

op="$1"

if [ "$op" = "get" ]; then
  token=$(heroku auth:token 2>/dev/null)
  if [ -n "$token" ]; then
    echo "username=heroku"
    echo "password=$token"
  fi
fi
# "store" and "erase" are no-ops: the credential always comes fresh from
# the Heroku CLI session, nothing to persist here.

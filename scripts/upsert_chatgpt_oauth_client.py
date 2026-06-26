import argparse
import secrets

from app_factory import create_app
from extensions import db
from models import OAuthClient


DEFAULT_SCOPES = (
    "openid profile email "
    "pets:read appointments:read clinical_summary:read consultations:read "
    "prescriptions:read exams:read vaccines:read handoff:read tutor_guidance:generate "
    "tutors:write pets:write appointments:write consultations:write exams:write"
)

CHATGPT_REDIRECT_URIS = "\n".join(
    [
        "https://chatgpt.com/connector/oauth/*",
        "https://chatgpt.com/aip/*/oauth/callback",
        "https://chat.openai.com/connector/oauth/*",
        "https://chat.openai.com/aip/*/oauth/callback",
    ]
)


def parse_args():
    parser = argparse.ArgumentParser(description="Create or update the ChatGPT OAuth client.")
    parser.add_argument("--client-id", default="petorlandia-chatgpt")
    parser.add_argument("--name", default="PetOrlandia ChatGPT")
    parser.add_argument("--rotate-secret", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    app = create_app()
    with app.app_context():
        client = OAuthClient.query.filter_by(client_id=args.client_id).first()
        created = client is None
        secret_value = None

        if created:
            secret_value = secrets.token_urlsafe(32)
            client = OAuthClient(
                client_id=args.client_id,
                client_secret=secret_value,
                name=args.name,
                redirect_uris=CHATGPT_REDIRECT_URIS,
                scopes=DEFAULT_SCOPES,
                is_confidential=True,
                auth_method="client_secret_post",
            )
            db.session.add(client)
        else:
            if args.rotate_secret or not client.client_secret:
                secret_value = secrets.token_urlsafe(32)
                client.client_secret = secret_value
            client.name = args.name
            client.redirect_uris = CHATGPT_REDIRECT_URIS
            client.scopes = DEFAULT_SCOPES
            client.is_confidential = True
            client.auth_method = "client_secret_post"

        db.session.commit()

        print(f"created={created}")
        print(f"client_id={client.client_id}")
        if secret_value:
            print(f"client_secret={secret_value}")
        else:
            print("client_secret=unchanged")
        print("auth_method=client_secret_post")
        print("redirect_uris:")
        print(client.redirect_uris)
        print("scopes:")
        print(client.scopes)


if __name__ == "__main__":
    main()

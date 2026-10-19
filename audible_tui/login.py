"""Accesso ad Audible Italia: apri l'URL nel browser, accedi (anche con OTP o
captcha) e incolla l'indirizzo della pagina su cui finisci."""
import audible
from .config import AUTH_FILE, CONFIG_DIR, LOCALE


def main() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    auth = audible.Authenticator.from_login_external(locale=LOCALE, with_username=False)
    auth.to_file(AUTH_FILE)
    AUTH_FILE.chmod(0o600)
    with audible.Client(auth) as c:
        print("Accesso riuscito:", c.get_user_profile().get("name") or "ok")
    print("Credenziali salvate in", AUTH_FILE)


if __name__ == "__main__":
    main()

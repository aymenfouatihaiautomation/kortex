"""Point d'intégration UNIQUE pour l'envoi d'email transactionnel (réinitialisation de mot de
passe). Phase 1 : aucun service réel n'est branché — appeler cette fonction sans configuration ne
doit JAMAIS planter le flux de réinitialisation, elle se contente de logger le lien, exactement
comme `bloc5_payment/routes.py` logge déjà le lien d'accès en mode mock faute de SMTP configuré.

POUR ACTIVER EN VRAI (choix produit/coût à faire séparément, pas décidé ici) : remplacer le corps
de `send_password_reset_email` par un appel à un service transactionnel (Postmark, Resend,
SendGrid, Amazon SES...). `accounts/service.py` et `accounts/routes.py` n'ont besoin d'AUCUN
changement — seule cette fonction doit être remplacée."""


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    print(
        f"[accounts][email] (non envoyé — aucun service transactionnel configuré) "
        f"Lien de réinitialisation pour {to_email} : {reset_url}"
    )

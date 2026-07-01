# Laptop Deals Telegram Bot

Version simple pour iPhone.

## Fichiers à uploader

Upload directement dans ton dépôt GitHub:
- main.py
- requirements.txt
- README.md
- laptop-deals.yml

Puis crée manuellement le vrai fichier GitHub Actions:

1. GitHub -> Add file -> Create new file
2. Nom exact:
.github/workflows/laptop-deals.yml
3. Colle tout le contenu de laptop-deals.yml
4. Commit changes
5. Tu peux supprimer laptop-deals.yml de la racine après.

## Secrets GitHub

Va dans:
Settings -> Secrets and variables -> Actions -> New repository secret

Ajoute:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- MAX_PRICE = 1000

## Lancer le bot

GitHub -> Actions -> Laptop Deals Telegram Bot -> Run workflow

Il se lance automatiquement vers 8h, 17h et 20h Montréal.

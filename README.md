# Laptop Deals Telegram Bot

Bot Telegram pour surveiller des laptops au Canada.

Critères par défaut:
- Budget max: 1000 CAD
- RTX 4050 / RTX 4060 / RTX 5050 / RTX 5060
- Lenovo LOQ / Legion
- ASUS TUF
- Acer Nitro
- HP Victus
- MSI Katana
- ThinkPad

## Fichiers nécessaires

À la racine du dépôt GitHub:
- `main.py`
- `requirements.txt`
- `README.md`
- `.gitignore`
- `.github/workflows/laptop-deals.yml`

Sur iPhone, le dossier `.github` peut être caché. Si tu ne le vois pas:
1. Upload d'abord `main.py`, `requirements.txt`, `README.md`.
2. Dans GitHub, clique `Add file` -> `Create new file`.
3. Nom du fichier:
   `.github/workflows/laptop-deals.yml`
4. Colle le contenu du fichier workflow.

## GitHub Secrets

Va dans:
Settings -> Secrets and variables -> Actions -> New repository secret

Ajoute:

### TELEGRAM_BOT_TOKEN
Token donné par BotFather.

### TELEGRAM_CHAT_ID
Ton chat id Telegram.

### MAX_PRICE
Exemple:
`1000`

### KEYWORDS
Optionnel:
`rtx 4050,rtx 4060,rtx 5050,rtx 5060,lenovo loq,lenovo legion,asus tuf,acer nitro,hp victus,msi katana,thinkpad`

## Lancer le bot

GitHub -> Actions -> Laptop Deals Telegram Bot -> Run workflow

Le bot tourne aussi automatiquement vers 8h, 17h et 20h Montréal.

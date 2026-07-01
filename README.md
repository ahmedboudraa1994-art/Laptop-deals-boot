# Laptop Deals Monitor

## Ce qui a été corrigé dans cette version

1. **Bug "je clique et je tombe sur un autre site"** — corrigé.
   Le scraper filtre maintenant strictement les liens :
   - il ignore tout lien qui ne pointe pas vers le même domaine que le site
     scrapé (donc plus de liens pub Criteo/Taboola/Google Ads/comparateurs
     de prix accidentellement récupérés) ;
   - après avoir suivi le lien, il vérifie que l'URL finale (après
     redirections) est toujours sur le même domaine — sinon le deal est
     rejeté plutôt qu'affiché avec un lien trompeur ;
   - le lien envoyé sur Telegram est toujours l'URL finale réellement
     visitée, jamais l'URL brute devinée depuis la page de recherche.

2. **Persistance de `seen_deals.json`** — le workflow GitHub Actions commit
   automatiquement ce fichier dans le repo après chaque run, donc les
   deals déjà vus ne seront plus renvoyés en boucle.

3. **Logs détaillés par site** — visibles dans l'onglet *Actions* de GitHub
   (bouton "Run" → logs), pour voir exactement quels sites répondent, lesquels
   bloquent, et lesquels redirigent.

4. **Confirmation Telegram** — vérifie le status code de l'envoi, réessaie,
   et découpe le message s'il est trop long.

## Limite connue (site JS-lourds)

Best Buy Canada, Walmart Canada, Costco Canada, Dell Canada et Newegg
Canada rendent une bonne partie de leur contenu en JavaScript et/ou ont une
protection anti-bot. Avec de simples requêtes HTTP (`requests`), ces sites
donneront souvent 0 résultat — ce n'est pas un bug, c'est une limite
technique. Si tu veux les couvrir correctement, il faudrait ajouter un
scraping par navigateur headless (Playwright), possible mais plus lourd à
faire tourner dans GitHub Actions. Dis-le-moi si tu veux que je l'ajoute.

## Installation

1. Crée un repo GitHub (ou utilise un repo existant).
2. Upload ces fichiers en gardant la structure exacte :
   ```
   ton-repo/
   ├── laptop_deals_monitor.py
   ├── requirements.txt
   ├── .github/
   │   └── workflows/
   │       └── deals.yml
   └── seen_deals.json   (créer un fichier vide contenant juste: [])
   ```
3. Va dans **Settings → Secrets and variables → Actions** et ajoute :
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Va dans **Settings → Actions → General → Workflow permissions** et coche
   **"Read and write permissions"** (nécessaire pour que le workflow puisse
   committer `seen_deals.json`).
5. Va dans l'onglet **Actions** du repo, sélectionne "Laptop Deals Monitor",
   et clique **"Run workflow"** pour tester manuellement.

## Ajuster les prix

Dans `.github/workflows/deals.yml`, modifie :
```yaml
MAX_PRICE: "1000"
MIN_PRICE: "600"
```

## Fréquence

Par défaut le workflow tourne toutes les 2h (`cron: "0 */2 * * *"`).
Modifie cette ligne dans `deals.yml` pour changer la fréquence.

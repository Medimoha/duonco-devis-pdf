# Service de génération automatique des devis PDF DUOnco

Ce service tourne en dehors de Claude et de Monday : une fois déployé, il
génère et attache le PDF du devis tout seul, à chaque clic sur le bouton
"Générer PDF", 24/7, sans aucune intervention.

## Déploiement (10 minutes, sur Render.com — gratuit pour ce cas d'usage)

### 1. Créer un jeton d'API Monday
1. Dans Monday, cliquez sur votre avatar (en bas à gauche) → **Administration**
2. Onglet **API** → copiez votre **jeton API personnel**
3. Gardez-le de côté, vous en aurez besoin à l'étape 4

### 2. Mettre ce code sur GitHub
1. Créez un compte GitHub si vous n'en avez pas (gratuit) : https://github.com/signup
2. Créez un nouveau dépôt (bouton vert **"New"**), nommez-le par ex. `duonco-devis-pdf`
3. Téléversez les 4 fichiers de ce dossier (`app.py`, `requirements.txt`, `Procfile`, `README.md`) via **"uploading an existing file"** sur la page du dépôt

### 3. Déployer sur Render
1. Créez un compte sur https://render.com (gratuit, connexion possible avec GitHub)
2. Cliquez **"New +"** → **"Web Service"**
3. Connectez votre dépôt GitHub `duonco-devis-pdf`
4. Render détecte automatiquement `Procfile` et `requirements.txt` — laissez les réglages par défaut
5. Choisissez le plan **Free**

### 4. Ajouter la variable d'environnement
1. Dans les réglages du service Render, section **Environment**
2. Ajoutez une variable : `MONDAY_API_TOKEN` = *(collez le jeton copié à l'étape 1)*
3. Cliquez **"Save Changes"** — Render redéploie automatiquement

### 5. Récupérer l'URL et me la donner
Une fois déployé, Render vous donne une URL du type :
`https://duonco-devis-pdf.onrender.com`

**Donnez-moi cette URL dans le chat** — je configurerai moi-même le webhook
Monday pour qu'il pointe vers `https://votre-url.onrender.com/webhook`.
C'est la seule étape technique qu'il me reste à faire, et elle prend
30 secondes une fois l'URL en main.

## Vérifier que ça marche

Une fois tout branché :
1. Ouvrez `https://votre-url.onrender.com/health` dans un navigateur → doit
   afficher `{"status": "ok"}`
2. Cliquez sur "Générer PDF" sur un devis dans Monday
3. Le PDF apparaît dans la colonne "PDF du devis" en quelques secondes

## Note sur le plan gratuit Render

Le plan gratuit met le service en veille après 15 minutes d'inactivité — le
premier clic après une pause peut prendre 30-50 secondes le temps qu'il se
réveille. Les clics suivants sont quasi instantanés. Si c'est gênant, un plan
payant à partir de ~7$/mois élimine cette latence.

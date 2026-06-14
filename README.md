# TikTok Video Bot

Bot Telegram qui crée automatiquement une vidéo TikTok verticale à partir d'un sujet.

Exemple :

```text
Sujet : comment choisir un bon ordinateur portable d’occasion au Sénégal
```

Le bot génère un script français adapté au public sénégalais, prépare un plan de 15 à 20 scènes, cherche des photos libres via Pexels et Pixabay, génère une voix française, ajoute des sous-titres, monte une vidéo MP4 verticale et l'envoie sur Telegram.

Le bot ne publie pas automatiquement sur TikTok. La publication reste manuelle.

## Fonctionnement

Gemini est utilisé uniquement pour :

- écrire le script ;
- créer le plan narratif ;
- définir un profil visuel cohérent ;
- générer les requêtes de recherche média ;
- proposer le titre et les hashtags.

Les visuels ne sont pas générés par IA. Ils viennent de photos royalty-free accessibles par API :

- Pexels ;
- Pixabay.

Si aucun média pertinent n'est disponible, le bot réutilise un média cohérent déjà sélectionné ou crée un visuel final de secours avec Pillow.

## Variables D'environnement

Le projet utilise uniquement :

```text
TELEGRAM_BOT_TOKEN=
GEMINI_API_KEY=
PEXELS_API_KEY=
PIXABAY_API_KEY=
PUBLIC_URL=
```

`PEXELS_API_KEY` ou `PIXABAY_API_KEY` suffit pour démarrer, mais il est recommandé de configurer les deux.

Ne pas utiliser de clé TikTok, ElevenLabs ou OpenAI. Ne pas ajouter de secret webhook.

## Créer Les Clés

Telegram :

1. Ouvre Telegram.
2. Cherche `@BotFather`.
3. Envoie `/newbot`.
4. Copie le token dans `TELEGRAM_BOT_TOKEN`.

Gemini :

1. Va sur Google AI Studio.
2. Crée une clé API.
3. Mets-la dans `GEMINI_API_KEY`.

Pexels :

1. Crée un compte développeur Pexels.
2. Copie ta clé API.
3. Mets-la dans `PEXELS_API_KEY`.

Pixabay :

1. Crée un compte Pixabay.
2. Récupère ta clé API.
3. Mets-la dans `PIXABAY_API_KEY`.

## Render

Build Command :

```bash
pip install -r requirements.txt
```

Start Command :

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Configure les variables dans Render :

```text
TELEGRAM_BOT_TOKEN
GEMINI_API_KEY
PEXELS_API_KEY
PIXABAY_API_KEY
PUBLIC_URL
```

`PUBLIC_URL` doit être l'URL Render sans `/webhook`, par exemple :

```text
https://ton-service.onrender.com
```

Au démarrage, le webhook Telegram est automatiquement défini sur :

```text
https://ton-service.onrender.com/webhook
```

## Endpoints

Santé :

```text
GET /health
```

Réponse :

```json
{"status":"ok","telegram_bot":"ready"}
```

Webhook Telegram :

```text
POST /webhook
```

## UptimeRobot

Pour limiter le sommeil Render Free, configure UptimeRobot sur :

```text
https://ton-service.onrender.com/health
```

## Utilisation

Dans Telegram :

```text
/start
```

Puis :

```text
Sujet : comment choisir un bon ordinateur portable d’occasion au Sénégal
```

Le bot envoie des messages de progression :

```text
✅ Sujet reçu. Je prépare la vidéo...
📝 Génération du script et du plan visuel...
🔎 Recherche des photos cohérentes...
🎞️ Sélection des visuels 1/18...
⬇️ Téléchargement et préparation des médias...
🎙️ Génération de la voix...
📝 Préparation des sous-titres...
🎬 Montage de la vidéo 1 min 02 s...
📤 Envoi de la vidéo...
```

## File D'attente

Render Free a peu de mémoire et de CPU. Le projet utilise donc :

- une seule file globale ;
- un seul worker vidéo ;
- une protection par utilisateur.

Un utilisateur ne peut pas lancer deux vidéos en même temps. Si une autre vidéo est déjà en cours, le sujet est ajouté à la file.

## Musique Et Police

Musique de fond :

```text
assets/music/background.mp3
```

Police personnalisée :

```text
assets/fonts/font.ttf
```

## Performance

Pour rester compatible Render Free, le bot télécharge uniquement des photos, pas de vidéos stock. La vidéo finale est rendue en 540x960, format vertical 9:16. C'est beaucoup plus léger et réduit les erreurs mémoire 512 MB.

La durée finale suit la durée réelle de la voix gTTS. La cible reste environ 1 min 02 s.

## Problèmes Fréquents

`/health` retourne Not Found :

- vérifie que le repo est à la racine ;
- vérifie le Start Command ;
- ne mets pas de Root Directory si les fichiers sont à la racine.

Webhook non configuré :

- vérifie `TELEGRAM_BOT_TOKEN` ;
- vérifie `PUBLIC_URL` sans `/webhook` ;
- redéploie Render.

Clé Pexels ou Pixabay absente :

- configure au moins une clé média ;
- deux clés donnent de meilleurs résultats.

Aucun média trouvé :

- le bot utilise un média précédent ou un visuel Pillow ;
- essaie un sujet plus concret.

Quota fournisseur atteint :

- le bot continue avec l'autre fournisseur si disponible.

Render dort :

- utilise UptimeRobot sur `/health`.

Vidéo trop lente :

- la recherche média, le téléchargement, gTTS et MoviePy peuvent prendre plusieurs minutes sur Render Free.

Erreur FFmpeg ou MoviePy :

- vérifie les logs Render ;
- relance un déploiement propre ;
- évite de lancer plusieurs générations.

Fichier Telegram trop grand :

- le projet compresse en H.264 avec un bitrate modéré ;
- la résolution 540x960 aide à rester sous la limite.

## Sécurité

- Ne commit jamais `.env`.
- Ne colle pas tes clés API dans le code.
- Les erreurs internes ne sont pas envoyées aux utilisateurs Telegram.
- Les téléchargements sont limités en taille.
- Seuls des formats image/vidéo connus sont traités.

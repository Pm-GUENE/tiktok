# TikTok Video Bot

Bot Telegram en Python qui génère automatiquement une vidéo TikTok verticale à partir d'un simple sujet.

Exemple :

```text
Sujet : comment choisir un bon ordinateur portable d’occasion au Sénégal
```

Le bot génère :

- un script en français adapté à une audience sénégalaise ;
- un plan vidéo de 15 à 20 scènes, 18 scènes par défaut ;
- des prompts d'images verticales 9:16 ;
- des images via Gemini quand l'API image est disponible ;
- une voix off française avec gTTS ;
- une vidéo MP4 verticale autour de 1 min 02 s ;
- des sous-titres lisibles ;
- un titre au début ;
- une musique de fond légère si `assets/music/background.mp3` existe ;
- un message final avec le titre et les hashtags.

Le bot n'envoie rien automatiquement sur TikTok. L'utilisateur publie la vidéo manuellement.

## Stack

- Python 3.11+
- FastAPI
- python-telegram-bot
- google-genai
- gTTS
- MoviePy
- FFmpeg
- Pillow
- Render Free Web Service

## Limite Gemini

Le projet respecte une limite prudente de 5 requêtes Gemini par minute.

Pour éviter les erreurs 429, toutes les requêtes Gemini passent par un limiteur centralisé qui attend environ 13 secondes entre deux appels. La génération du script compte comme une requête. Chaque image compte aussi comme une requête.

Une vidéo avec 18 images peut donc prendre plusieurs minutes. Ce délai est normal. Le bot envoie des messages de progression pendant la génération.

Si Gemini refuse une image ou renvoie trop d'erreurs, le bot crée une image de secours avec Pillow et continue le montage.

## Créer le bot Telegram

1. Ouvre Telegram.
2. Cherche `@BotFather`.
3. Envoie `/newbot`.
4. Choisis un nom puis un username terminé par `bot`.
5. Copie le token fourni par BotFather.

Ce token est la variable :

```text
TELEGRAM_BOT_TOKEN
```

## Obtenir la clé Gemini

1. Va dans Google AI Studio.
2. Crée une clé API Gemini.
3. Copie la clé dans :

```text
GEMINI_API_KEY
```

Le projet utilise le SDK officiel `google-genai`.

## Variables d'environnement

Le projet utilise uniquement ces trois variables :

```text
TELEGRAM_BOT_TOKEN=
GEMINI_API_KEY=
PUBLIC_URL=
```

`PUBLIC_URL` est l'URL publique Render, par exemple :

```text
https://tiktok-video-bot.onrender.com
```

Le webhook Telegram sera automatiquement configuré au démarrage sur :

```text
https://tiktok-video-bot.onrender.com/webhook
```

Il n'y a pas de variable secrète pour le webhook, pas de variable d'environnement applicative supplémentaire, pas de clé ElevenLabs et pas de clé TikTok.

## Lancer en local

Installe FFmpeg sur ta machine, puis :

```bash
cd tiktok-video-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Remplis `.env` :

```text
TELEGRAM_BOT_TOKEN=ton_token_telegram
GEMINI_API_KEY=ta_cle_gemini
PUBLIC_URL=https://ton-url-publique
```

Pour tester un webhook en local, il faut une URL publique, par exemple via un tunnel. Ensuite :

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Vérifie :

```text
http://localhost:8000/health
```

Réponse attendue :

```json
{
  "status": "ok",
  "telegram_bot": "ready"
}
```

## Déploiement Render Free

1. Pousse ce projet sur GitHub.
2. Dans Render, crée un nouveau `Web Service`.
3. Connecte le dépôt.
4. Render peut utiliser `render.yaml`.
5. Configure les variables d'environnement :

```text
TELEGRAM_BOT_TOKEN
GEMINI_API_KEY
PUBLIC_URL
```

Exemple de `PUBLIC_URL` :

```text
https://tiktok-video-bot.onrender.com
```

Render lancera :

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Le bot utilise un webhook, pas le long polling. C'est adapté à Render.

## UptimeRobot

Render Free peut dormir après une période d'inactivité. Pour réduire ce problème, configure UptimeRobot avec une surveillance HTTP sur :

```text
https://your-render-app.onrender.com/health
```

Remplace `your-render-app` par le nom réel du service Render.

## Utilisation

Dans Telegram, envoie :

```text
/start
```

Puis :

```text
Sujet : comment choisir un bon ordinateur portable d’occasion au Sénégal
```

Le bot répondra avec des messages comme :

```text
✅ Sujet reçu. Je prépare la vidéo...
📝 Génération du script long...
🎨 Préparation des 15 à 20 scènes visuelles...
🎨 Génération des visuels 1/18...
🎙️ Génération de la voix...
🎬 Montage de la vidéo 1 min 02 s...
📤 Envoi de la vidéo...
```

Ensuite il envoie le MP4, puis le titre et les hashtags.

## Ajouter une musique de fond

Place un fichier nommé exactement :

```text
assets/music/background.mp3
```

Le volume est automatiquement réduit autour de 10 % pour garder la voix claire.

## Ajouter une police personnalisée

Place une police nommée exactement :

```text
assets/fonts/font.ttf
```

Elle sera utilisée pour les titres, sous-titres et images de secours.

## Protection contre la surcharge

Le projet contient une protection simple en mémoire :

- un même utilisateur ne peut pas lancer deux générations en même temps ;
- une seule génération lourde tourne à la fois ;
- les requêtes Gemini ne sont pas parallélisées ;
- les images sont générées une par une.

Ne spamme pas plusieurs demandes de vidéo. Sur Render Free, cela peut ralentir ou faire échouer le service.

## Problèmes fréquents

### Le webhook ne se configure pas

Vérifie que `PUBLIC_URL` est bien l'URL publique Render sans `/webhook` à la fin. Le projet ajoute `/webhook` automatiquement.

### `TELEGRAM_BOT_TOKEN` manquant

Ajoute la variable dans Render ou dans `.env` en local. Le token vient de BotFather.

### `GEMINI_API_KEY` manquant

Ajoute ta clé Gemini dans Render ou dans `.env`.

### `PUBLIC_URL` manquant

Ajoute l'URL publique Render, par exemple :

```text
https://tiktok-video-bot.onrender.com
```

### Render dort

Render Free peut mettre le service en veille. Utilise UptimeRobot sur `/health`.

### La génération est trop lente

C'est normal si 15 à 20 images sont générées. Le projet attend environ 13 secondes entre les appels Gemini pour respecter la limite de 5 requêtes par minute.

### Erreur Gemini 429

Le bot attend 60 secondes et réessaie jusqu'à 3 fois. Si l'image échoue encore, il crée une image de secours avec Pillow.

### Erreur gTTS

gTTS dépend d'une connexion externe. Réessaie plus tard si la génération de voix échoue.

### Erreur MoviePy ou FFmpeg

Vérifie que FFmpeg est disponible. Render installe généralement FFmpeg dans l'environnement Python de MoviePy, mais selon l'image système il peut être nécessaire d'ajuster le service ou d'ajouter un build pack.

### Vidéo trop lourde pour Telegram

Le projet compresse en H.264 avec un bitrate raisonnable. Si une vidéo dépasse encore la limite, réduis le nombre de scènes ou baisse le bitrate dans `services/video_service.py`.

## Structure

```text
tiktok-video-bot/
├── main.py
├── requirements.txt
├── render.yaml
├── README.md
├── .env.example
├── .gitignore
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── bot.py
│   ├── routes.py
│   └── utils.py
├── services/
│   ├── __init__.py
│   ├── gemini_service.py
│   ├── voice_service.py
│   ├── video_service.py
│   ├── subtitle_service.py
│   └── rate_limiter.py
├── assets/
│   ├── music/
│   ├── fonts/
│   └── backgrounds/
└── output/
    ├── images/
    ├── audio/
    └── videos/
```

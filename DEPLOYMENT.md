# Deployment Guide: N-VISION

Diese Anleitung beschreibt, wie die N-VISION Anwendung in einer Docker-Umgebung bereitgestellt wird.

## Voraussetzungen

- Server mit Docker und Docker Compose installiert
- Git zum Klonen des Repositories
- (Optional) Reverse Proxy wie Traefik oder Nginx für SSL/TLS

## 1. Vorbereitung auf dem Server

Klonen Sie das Repository auf den Server:

```bash
git clone [REPOSITORY_URL]
cd nvision
```

## 2. Konfiguration

Die Anwendung nutzt Umgebungsvariablen für sicherheitsrelevante Einstellungen. In der `docker-compose.yml` können diese angepasst werden:

- `SECRET_KEY`: Ein sicherer Schlüssel für die JWT-Token-Generierung.
- `DATABASE_URL`: Pfad zur SQLite-Datenbank.

Stellen Sie sicher, dass die Datenbankdateien für den Docker-Container beschreibbar sind oder die entsprechenden Volumes korrekt gemappt sind.

## 3. Deployment starten

Starten Sie die Anwendung mit Docker Compose:

```bash
docker compose up -d --build
```

Die Anwendung ist standardmäßig unter Port `8001` erreichbar (Mapping `8001:8000`).

## 4. Validierung

Prüfen Sie den Status des Containers:

```bash
docker compose ps
```

Logs einsehen:

```bash
docker compose logs -f app
```

## 5. Architektur-Details

- **Backend**: FastAPI (Python 3.12)
- **Paketverwaltung**: uv (Astral)
- **Datenbank**: SQLite (`n-vision.db`)
- **Container**: Multi-stage Build für minimale Image-Größe

## Wartung

- **Updates**: 
  ```bash
  git pull
  docker compose up -d --build
  ```
- **Backup**: Sichern Sie regelmäßig die Datei `n-vision.db` im Projektverzeichnis.
- **Reset**: Über den Button "Daten resetten" in der UI (Admin-Bereich) können Testdaten neu generiert werden.

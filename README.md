# Runner Control — GitHub Actions Uzak Masaüstü Paneli

GitHub Actions runner'larını (Linux/Kasm ve Windows/VNC) web arayüzünden başlat, izle,
bağlan, dosya al/ver ve durdur. Panel Codespace içinde **private** çalışır.

## İçerik

```
runner-control/
├─ index.html                       # Kontrol paneli (tek dosya, bağımlılık yok)
├─ backend/main.py                  # FastAPI backend iskeleti (dispatch + webhook + cancel)
└─ .github/workflows/
   ├─ kasm-linux.yml                # Linux + Kasm Desktop + cloudflared + filebrowser
   └─ windows-vnc.yml               # Windows + TightVNC + noVNC + cloudflared + filebrowser
```

## Mimari

```
[index.html]  ──POST /runners──►  [FastAPI backend]  ──workflow_dispatch──►  [GitHub Actions]
     ▲                                   ▲                                    │
     └──GET /runners (poll)───────────┘        ◄──POST /webhook/tunnel────────┘
                                  (tünel URL'leri: vnc_url + files_url)
```

- **correlation_id**: `workflow_dispatch` run_id dönmez. Backend her başlatmada bir
  `correlation_id` üretir, workflow bunu `run-name`'e yazar; eşleştirme böyle yapılır.
- **Tünel URL'i**: log'dan okumak yerine runner, hazır olunca backend'e **webhook** atar
  (anında + güvenilir). Log okuma yalnızca yedek.
- **Dosya al/ver**: her runner'da **filebrowser** (6902) çalışır, ayrı bir tünelle açılır.
- **Süre**: workflow içinde self-timeout (`sleep`) + panelden "Durdur" (GitHub cancel).

## Kurulum

1. Bu iki workflow'u repo'nun `.github/workflows/` klasörüne koy.
2. Repo **Settings > Secrets and variables > Actions** altına ekle:
   - `BACKEND_URL`  — backend'in public URL'i (Codespace public port veya cloudflared)
   - `WEBHOOK_SECRET` — backend ile aynı gizli token
3. Backend'i Codespace'te çalıştır:
   ```bash
   pip install fastapi uvicorn httpx
   export GH_TOKEN=ghp_xxx GH_OWNER=<owner> GH_REPO=<repo> WEBHOOK_SECRET=super-secret
   uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```
4. `index.html`'i aç (şu an mock verilerle canlı çalışır). Gerçek backend'e bağlamak için
   JS'teki `machines` mock'unu `GET /runners` fetch'i ile değiştir.

## Endpoint’ler

| Metod | Yol | Açıklama |
|---|---|---|
| POST | `/runners` | Makine(ler) başlat (os, image, tunnel_provider, duration_minutes, count) |
| GET | `/runners` | Durum + tünel URL listesi |
| DELETE | `/runners/{correlation_id}` | Durdur (GitHub run cancel) |
| POST | `/webhook/tunnel` | Runner buraya tünel URL'lerini bildirir (X-Webhook-Token) |

## Uyarılar

- GitHub-hosted runner'da imaj sabittir (Windows'ta base imaj seçilemez); Linux'ta
  container/imaj seçebilirsin.
- Codespace uyursa webhook kaçar — runner başlatmadan önce Codespace açık olmalı.
- `trycloudflare` quick tunnel'lar 20 paralelde throttle olabilir; kararlılık için
  token'lı named tunnel kullan.
- Interaktif uzak masaüstü kullanımı GitHub AUP açısından gri alandır; kısa/gözlem
  amaçlı kullan ve yedeklerini başka yerde tut.

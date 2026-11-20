<p align="center"><img src="assets/icon.png" width="128" alt="Logo RouteRewind"></p>

<h1 align="center">RouteRewind</h1>

<p align="center">
Ricostruzione e animazione su mappa del percorso di un segnaposto, a partire da file con coordinate e data/ora.<br>
di <b>Giovanni Ciccarese</b>
</p>

<p align="center">
<a href="../../actions/workflows/tests.yml"><img src="https://github.com/gcblack1984/RouteRewind/actions/workflows/tests.yml/badge.svg" alt="Test"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/licenza-MIT-blue" alt="Licenza MIT"></a>
<img src="https://img.shields.io/badge/Windows-10%2F11-0078D6" alt="Windows 10/11">
</p>

> *English:* RouteRewind reads coordinates and timestamps from PDF, Excel, CSV, Word, GPX, KML, GeoJSON and more, draws the route on a map and replays it with adjustable speed. Offline maps and HTML/PDF reports included. The interface is in Italian.

## Scarica

- **Microsoft Store**: [RouteRewind](https://apps.microsoft.com/detail/9P41JC57SPDS) (disponibile dopo la certificazione).
- **GitHub**: l'ultima versione per Windows è nella pagina [Releases](../../releases/latest): scarica lo zip, estrailo e avvia `RouteRewind.exe`.

## Funzioni

- **Apertura file** trascinandoli sulla finestra, con *Apri* (Ctrl+O) o da riga di comando.
- **Formati**: PDF, CSV/TSV/TXT, XLSX/XLSM, XLS (con xlrd), DOCX, GPX, KML/KMZ, GeoJSON, JSON (anche Google Takeout), NMEA, HTML.
- **Riconoscimento automatico** delle colonne (Lat/Latitudine, Lon/Longitudine, Coordinate, Data, Ora, Timestamp…) o ricerca nel testo libero: decimali con punto o virgola, gradi-primi-secondi, N/S/E/W, link Google Maps, date italiane e ISO, epoch, seriali Excel. I punti vengono riordinati per data e ora.
- **Animazione** con Avvia/Pausa e due modalità di velocità: uniforme (punti al secondo) o tempo reale accelerato (fino a ×86400).
- **Cursore sulla cronologia** per scegliere il punto di partenza; clic su un punto della mappa o della tabella per saltarci. Tasti: Spazio, ← →, Home.
- **Mappe offline**: salva l'area del percorso (mappa OpenStreetMap di Protomaps) o importa file `.pmtiles`. Senza connessione l'app passa da sola alla mappa offline; le mappe viste online restano in cache fino a 512 MB.
- **Report** HTML interattivo e PDF, per l'intero percorso o dal punto attuale.
- Splash all'avvio, nome dell'autore su splash, barra del titolo e finestra Informazioni.

## Avvio da sorgente

Serve Python 3.11 o successivo.

```
pip install -r requirements.txt
python main.py
```

Le mappe online richiedono Internet. Per le mappe offline anche avviando da sorgente, esegui una volta `build.bat`: scarica Leaflet e protomaps-leaflet in `web\leaflet` e `web\lib`.

Le mappe offline sono salvate in `%LOCALAPPDATA%\RouteRewind\offline`.

## Creare l'exe e il pacchetto per Microsoft Store

1. `build.bat` crea `dist\RouteRewind\RouteRewind.exe`.
2. Su [Partner Center](https://partner.microsoft.com/dashboard) riserva il nome e copia i dati di *Identità del prodotto* in `packaging\AppxManifest.xml`.
3. `make_msix.bat` (richiede il Windows SDK) crea `dist\RouteRewind.msix` da caricare in Partner Center.

Pubblicando un tag `v*` su GitHub, il workflow *Release* crea l'exe e lo allega alla release.

## Test

```
pip install -r requirements-dev.txt
python -m pytest tests
```

`tests/make_samples.py` crea file di esempio in tutti i formati nella cartella `tests/samples`.

## Struttura

| File | Contenuto |
| --- | --- |
| `main.py` | avvio e splash |
| `main_window.py` | finestra principale, animazione, report |
| `parsers.py` | lettura dei formati e ricerca di coordinate e date |
| `pmtiles_extract.py`, `offline.py`, `offline_ui.py` | mappe offline |
| `report.py`, `track.py` | report e statistiche del percorso |
| `web/map.html` | mappa (Leaflet) |
| `packaging/` | manifest e immagini per Microsoft Store |

## Licenza e privacy

Codice rilasciato con licenza [MIT](LICENSE). Componenti di terze parti in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). L'app non raccoglie dati: vedi [PRIVACY.md](PRIVACY.md).

Mappe © OpenStreetMap contributors, © CARTO, Esri; mappe offline Protomaps (dati OpenStreetMap, ODbL).

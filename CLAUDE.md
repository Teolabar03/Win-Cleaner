# CLAUDE.md

## Cos'è

**Win-Cleaner** (nell'interfaccia "Pulizia disco"): exe portable per Windows che mappa un disco, classifica cartelle e
file pesanti con **Rizzo Flow** (in-process, llama.cpp, modello Spark-X2.5-4B Q8_0) e propone cosa
eliminare. L'utente cambia le spunte, apre i percorsi in Esplora file, conferma due volte; di default
va tutto nel Cestino. Interfaccia in stile Windows 11 (Fluent): Segoe UI Variable, Segoe Fluent Icons,
colore principale e tema chiaro/scuro letti dal registro di Windows.

Repository pubblico. Testi dell'interfaccia in italiano; codice, commenti e docstring in inglese.

## Comandi

```bash
uv sync                                   # dipendenze; rizzo-flow da GitHub, fissato al commit d34665b
.venv/Scripts/python -m cleaner           # avvia l'app in sviluppo (modello e runtime presi da ../rizzo-flow)
.venv/Scripts/python -m pytest -q         # test di sicurezza, raggruppamento, eliminazione (nessun modello)
powershell -File build.ps1                # dist\Cleaner: exe + _internal + ai\ (hard link a modello e runtime)
powershell -File build.ps1 -NoAi          # solo exe, senza modello
```

`CLEANER_AI_DIR` forza la cartella di modello/runtime; `CLEANER_DEBUG=1` apre gli strumenti di sviluppo
di WebView2. Registro in `registri\cleaner.log`, un JSON per ogni pulizia in `registri\pulizia_*.json`
(accanto all'exe; in sviluppo nella radice del progetto).

Anteprima dell'interfaccia senza pywebview: servire `src/cleaner/ui` con uno script che definisca
`window.pywebview.api` (vedi i metodi di `app.Api`) e i dati di un'analisi vera salvati in JSON.

## Architettura

`scanner.py` (os.scandir iterativo, solo cartelle in memoria, salta giunzioni e segnaposto OneDrive;
C: con 2,1 M file in ~50 s) → `grouping.py` (albero → ~600 elementi: regole di spazzatura, unità
progetto/app/gioco/dati app, file grandi, cartelle ≥ 64 MB, aree protette divise per sottocartella;
ogni byte appartiene a un solo elemento, `size` esclusivo per i grafici, `free` = quanto libera
eliminarlo; `merge` unisce le cache piccole per programma) → `classifier.py` (due domande per
elemento sullo stesso stato: `category` choice + `deletable` boolean; ~125 ms/elemento su RTX 4070
SUPER; senza modello si usano regole ed estensioni) → `decide` (pre-selezione) → UI →
`deleter.py`.

- `rules.py`: tutto il sapere deterministico. `protection()` (Windows, Programmi, ProgramData,
  AppData\Local\Programs, WindowsApps, cartelle di avvio e ripristino) e `critical()` (radici, Users,
  profilo, cartelle note come Desktop/Documenti/Download) non si superano mai. `match()` riconosce le
  posizioni di spazzatura; nelle aree protette valgono solo le regole di sistema esatte
  (`system_only`). `node_modules` conta solo accanto a un `package.json` e fuori da AppData.
- **Pre-selezione prudente** (scelta dell'utente): spuntato solo ciò che ha una regola con
  `precheck` (cache, temp, registri, cache dei gestori di pacchetti) e che l'AI non contesta
  (p_delete ≥ 0,35), oppure, senza regola, cache/registri con p_category ≥ 0,7 e p_delete ≥ 0,9 e
  **mai** una cartella unità (programma, gioco, progetto, dati app). `node_modules`, venv, installer in
  Download, cache Gradle/NuGet/Maven, Windows.old e Cestino sono in elenco ma non spuntati.
- `deleter.guard` ricontrolla ogni percorso subito prima di toccarlo: protetto, critico, cartella
  dell'app, e **percorso reale diverso da quello lessicale** (giunzioni, symlink, unità SUBST) →
  rifiutato. Le regole `contents_only` (Temp, WER, SoftwareDistribution\Download…) svuotano la
  cartella senza toglierla; dentro la cartella di una regola la protezione di sistema non si
  applica, solo lì. Il Cestino si svuota per primo, prima di spostarvi altro.
- **Interruzioni**: `stop_scan` ferma la mappatura e prosegue con la parte letta (`Node.complete`
  falso sulle cartelle lette a metà → `grouping.Builder.add` le rende non selezionabili, perché
  eliminarle toglierebbe anche il non visto); `skip_ai` ferma la classificazione e mostra i risultati
  (gli elementi non analizzati restano alle sole regole). "Annulla analisi" (`cancel`) scarta tutto.
- **Chiavette e telefoni.** `drives()` elenca unità fisse e rimovibili con lettera più le memorie
  dei dispositivi portatili (`mtp.devices()`, via Shell `Namespace(17)`); ogni unità ha `trash`
  (Cestino disponibile: solo dischi fissi). Senza Cestino la UI forza "Elimina definitivamente" e
  `deleter.remove` rifiuta comunque lo spostamento nel Cestino (`has_recycle_bin`): `send2trash` su
  una chiavetta eliminerebbe per sempre senza dirlo. Soglie adattive (`app.thresholds`): elementi da
  1/2000 del disco (4–64 MB), file grandi da 1/256 (32–512 MB).
- **Telefoni (MTP)**, `mtp.py`: niente lettera di unità, solo oggetti Shell con percorsi opachi. I
  percorsi leggibili sono `mtp:\Dispositivo\Memoria\...` (`rules.PHONE`; `rules.norm` li mette solo
  in minuscolo) e `mtp.REGISTRY` li traduce nei percorsi Shell. `PhoneScanner` produce lo stesso
  albero del disco (lento: un giro USB per cartella; interrompibile). Regole proprie
  (`phone_protection`: Android/data e obb; `phone_critical`: radice, cartelle principali, Rullino;
  `phone_match`: `.thumbnails`, cache delle app, `.Statuses` e `Sent` di WhatsApp, LOST.DIR).
  Eliminazione con IFileOperation senza annullamento, sempre definitiva. `tests/test_phone.py`
  prova tutto su una cartella normale registrata come telefono: Shell e IFileOperation si
  comportano allo stesso modo. **Mai provato su un telefono vero** (al 2026-09-28).
- `app.py`: ponte pywebview (`Api`, polling dal JS), una sola analisi o pulizia per volta; il modello
  si carica in background all'avvio (CUDA se c'è il driver NVIDIA, poi Vulkan, poi CPU; se fallisce
  l'app resta utilizzabile con le regole).
- UI: `ui/index.html`, `style.css` (token Fluent, chiaro/scuro), `app.js` (schermate home → analisi
  → risultati con anello, barra, elenco a gruppi espandibili, treemap squarified → conferma in due
  passi, la seconda chiede di scrivere ELIMINA se definitiva → esito). Nessuna risorsa esterna.

## Regole del progetto

- Mai indebolire `protection`/`critical`/`guard` per far comparire più spazio recuperabile.
- Ogni nuova regola di spazzatura: `precheck=True` solo se il contenuto si ricrea da solo senza
  perdita (cache, temp, registri). Aggiungere un test in `tests/test_safety.py`.
- La probabilità del modello non è calibrata (vedi la scheda di rizzo-flow): da sola non basta mai
  a spuntare un'intera cartella.
- Le patch via heredoc bash possono perdere i backslash: per stringhe con `\` usare Edit/Write o
  `chr(92)`.

## Stato (2026-09-28)

v0.1.0 costruita e provata sul PC di sviluppo (Windows 11, RTX 4070 SUPER): analisi di C: completa in
~110 s (622 elementi, 53 GB pre-selezionati, tutte cache). Non ancora provata su PC senza GPU
NVIDIA (Vulkan/CPU) né con Windows 10. Revisione di sicurezza fatta con Codex: corretti giunzioni e
SUBST, ordine del Cestino, analisi concorrenti, pre-selezione solo-AI e pre-selezione per età.
